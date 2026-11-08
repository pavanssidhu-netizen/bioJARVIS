"""Domain-Specific PyTorch Microfluidic Bubble Patch Classifier (BubblePatchCNN).

Provides a lightweight, fast PyTorch Convolutional Neural Network trained to
distinguish genuine phase-contrast microfluidic gas bubbles (dark refractive
meniscus ring + bright central Fresnel highlight) from optical channel-wall
glare streaks, dust specks, and clipped border artifacts.

If `models/labmate_patch_cnn.pt` does not exist on disk (e.g. on a fresh clone
where binary `.pt` files are gitignored), `get_patch_classifier()` automatically
trains the network in ~2 seconds on a curated procedural physics dataset (using
training seeds 9000..9500, strictly disjoint from the held-out evaluation seeds
1001..1018) and saves `evals/patch_cnn_metrics.json`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Tuple

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEIGHTS_PATH = REPO_ROOT / "models" / "labmate_patch_cnn.pt"
DEFAULT_METRICS_PATH = REPO_ROOT / "evals" / "patch_cnn_metrics.json"


class BubblePatchCNN(nn.Module):
    """3-stage Convolutional Neural Network for 48x48 grayscale phase-contrast patches.

    Outputs:
    - logit: binary classification logit (true intact microfluidic bubble vs. optical artifact)
    """

    def __init__(self) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 16, kernel_size=3, padding=1),
            nn.BatchNorm2d(16),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),  # 24x24
            nn.Conv2d(16, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),  # 12x12
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((4, 4)),
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Linear(64 * 4 * 4, 64),
            nn.ReLU(inplace=True),
            nn.Dropout(0.15),
            nn.Linear(64, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        feat = self.features(x)
        return self.classifier(feat).squeeze(-1)


def _generate_synthetic_patch(rng: np.random.Generator, is_positive: bool, size: int = 48) -> np.ndarray:
    """Synthesise a 48x48 microfluidic phase-contrast patch for training/validation."""
    bg = float(rng.uniform(165.0, 210.0))
    patch = np.full((size, size), bg, dtype=np.float32)
    yy, xx = np.mgrid[0:size, 0:size]
    patch += rng.normal(0.0, 3.0, size=(size, size)).astype(np.float32)

    if is_positive:
        # True intact bubble: dark refractive rim + bright inner highlight
        cx = float(rng.uniform(size * 0.38, size * 0.62))
        cy = float(rng.uniform(size * 0.38, size * 0.62))
        rx = float(rng.uniform(size * 0.22, size * 0.36))
        ry = float(rng.uniform(size * 0.18, size * 0.34))
        angle = float(rng.uniform(-0.4, 0.4))
        cos_a, sin_a = np.cos(angle), np.sin(angle)
        dx = xx - cx
        dy = yy - cy
        x_rot = dx * cos_a + dy * sin_a
        y_rot = -dx * sin_a + dy * cos_a
        r_norm = np.sqrt((x_rot / max(rx, 1.0)) ** 2 + (y_rot / max(ry, 1.0)) ** 2)

        rim_mask = (r_norm >= 0.72) & (r_norm <= 1.06)
        core_mask = r_norm < 0.72
        halo_mask = (r_norm > 1.06) & (r_norm <= 1.22)

        rim_darkness = float(rng.uniform(32.0, 105.0))
        core_bright = float(rng.uniform(185.0, 245.0))
        patch[rim_mask] = rim_darkness + 20.0 * np.abs(r_norm[rim_mask] - 0.90)
        patch[core_mask] = core_bright - 18.0 * (r_norm[core_mask] / 0.72) ** 2
        patch[halo_mask] = np.clip(patch[halo_mask] + 14.0, 0, 255)
    else:
        artifact_kind = int(rng.integers(0, 3))
        if artifact_kind == 0:
            # Specular channel wall glare streak
            y0 = int(rng.integers(8, size - 8))
            thickness = int(rng.integers(2, 6))
            patch[max(0, y0 - thickness) : min(size, y0 + thickness), :] = float(
                rng.uniform(235.0, 255.0)
            )
            patch[max(0, y0 + thickness) : min(size, y0 + thickness + 3), :] = float(
                rng.uniform(80.0, 125.0)
            )
        elif artifact_kind == 1:
            # Uniform dark dust/debris blob without bright Fresnel core
            cx = float(rng.uniform(size * 0.3, size * 0.7))
            cy = float(rng.uniform(size * 0.3, size * 0.7))
            r = float(rng.uniform(size * 0.15, size * 0.32))
            dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
            patch[dist <= r] = float(rng.uniform(45.0, 110.0))
        else:
            # Clipped edge meniscus at patch boundary
            edge_cx = 0.0 if rng.random() < 0.5 else float(size)
            cy = float(rng.uniform(size * 0.25, size * 0.75))
            r = float(rng.uniform(size * 0.25, size * 0.42))
            dist = np.sqrt((xx - edge_cx) ** 2 + (yy - cy) ** 2)
            rim = (dist >= 0.7 * r) & (dist <= 1.05 * r)
            patch[rim] = float(rng.uniform(45.0, 95.0))

    patch = cv2.GaussianBlur(np.clip(patch, 0, 255).astype(np.uint8), (3, 3), 0.6)
    return patch.astype(np.float32) / 255.0


def train_and_save_patch_cnn(
    weights_path: Path = DEFAULT_WEIGHTS_PATH,
    metrics_path: Path = DEFAULT_METRICS_PATH,
    epochs: int = 18,
) -> Tuple[BubblePatchCNN, Dict[str, Any]]:
    """Train `BubblePatchCNN` on disjoint synthetic microfluidic patches and save metrics."""
    torch.manual_seed(9001)
    rng_train = np.random.default_rng(9001)
    rng_val = np.random.default_rng(9501)

    n_train = 320
    n_val = 120

    x_train = np.zeros((n_train, 1, 48, 48), dtype=np.float32)
    y_train = np.zeros(n_train, dtype=np.float32)
    for i in range(n_train):
        label = 1 if i % 2 == 0 else 0
        x_train[i, 0] = _generate_synthetic_patch(rng_train, is_positive=bool(label))
        y_train[i] = float(label)

    x_val = np.zeros((n_val, 1, 48, 48), dtype=np.float32)
    y_val = np.zeros(n_val, dtype=np.float32)
    for i in range(n_val):
        label = 1 if i % 2 == 0 else 0
        x_val[i, 0] = _generate_synthetic_patch(rng_val, is_positive=bool(label))
        y_val[i] = float(label)

    model = BubblePatchCNN()
    criterion = nn.BCEWithLogitsLoss()
    optimizer = optim.AdamW(model.parameters(), lr=2.5e-3, weight_decay=1e-4)

    x_tr_t = torch.from_numpy(x_train)
    y_tr_t = torch.from_numpy(y_train)
    x_va_t = torch.from_numpy(x_val)
    y_va_t = torch.from_numpy(y_val)

    history = []
    batch_size = 32
    for epoch in range(1, epochs + 1):
        model.train()
        perm = torch.randperm(n_train)
        epoch_loss = 0.0
        for start in range(0, n_train, batch_size):
            idx = perm[start : start + batch_size]
            optimizer.zero_grad()
            logits = model(x_tr_t[idx])
            loss = criterion(logits, y_tr_t[idx])
            loss.backward()
            optimizer.step()
            epoch_loss += float(loss.item()) * len(idx)
        train_loss = epoch_loss / n_train

        model.eval()
        with torch.no_grad():
            val_logits = model(x_va_t)
            val_loss = float(criterion(val_logits, y_va_t).item())
            preds = (torch.sigmoid(val_logits) >= 0.5).float()
            val_acc = float((preds == y_va_t).float().mean().item())
            tp = float(((preds == 1) & (y_va_t == 1)).sum().item())
            fp = float(((preds == 1) & (y_va_t == 0)).sum().item())
            fn = float(((preds == 0) & (y_va_t == 1)).sum().item())
            val_f1 = (2 * tp) / max(2 * tp + fp + fn, 1.0)

        history.append(
            {
                "epoch": epoch,
                "train_loss": round(train_loss, 4),
                "val_loss": round(val_loss, 4),
                "val_accuracy": round(val_acc, 4),
                "val_f1": round(val_f1, 4),
            }
        )

    weights_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), weights_path)

    metrics = {
        "model_name": "BubblePatchCNN (PyTorch 3-Conv2d Microfluidic Phase-Contrast Verifier)",
        "architecture": "Conv2d(1->16->32->64) + BatchNorm2d + AdaptiveAvgPool2d + Linear(1024->64->1)",
        "train_samples": n_train,
        "val_samples": n_val,
        "disjoint_seed_policy": "Training seeds 9001/9501 strictly disjoint from held-out eval seeds 1001..1018",
        "final_val_accuracy": history[-1]["val_accuracy"],
        "final_val_f1": history[-1]["val_f1"],
        "final_val_loss": history[-1]["val_loss"],
        "epochs": history,
    }
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    model.eval()
    return model, metrics


_CACHED_MODEL: BubblePatchCNN | None = None


def get_patch_classifier() -> BubblePatchCNN:
    """Return a loaded (or freshly trained) `BubblePatchCNN` in eval mode."""
    global _CACHED_MODEL
    if _CACHED_MODEL is not None:
        return _CACHED_MODEL

    if DEFAULT_WEIGHTS_PATH.exists():
        try:
            model = BubblePatchCNN()
            state = torch.load(DEFAULT_WEIGHTS_PATH, map_location="cpu", weights_only=True)
            model.load_state_dict(state)
            model.eval()
            _CACHED_MODEL = model
            return model
        except Exception:
            pass

    model, _ = train_and_save_patch_cnn()
    _CACHED_MODEL = model
    return model


def score_bubble_patch_pytorch(
    gray: np.ndarray,
    bbox_xywh: Tuple[int, int, int, int],
) -> float:
    """Crop a padded ROI around `bbox_xywh` and return `BubblePatchCNN` probability in [0, 1]."""
    h, w = gray.shape[:2]
    bx, by, bw, bh = bbox_xywh
    pad_x = max(4, int(round(bw * 0.22)))
    pad_y = max(4, int(round(bh * 0.22)))
    x0 = max(0, bx - pad_x)
    y0 = max(0, by - pad_y)
    x1 = min(w, bx + bw + pad_x)
    y1 = min(h, by + bh + pad_y)
    crop = gray[y0:y1, x0:x1]
    if crop.size == 0:
        return 0.5
    resized = cv2.resize(crop, (48, 48), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    tensor = torch.from_numpy(resized).unsqueeze(0).unsqueeze(0)
    model = get_patch_classifier()
    with torch.no_grad():
        prob = float(torch.sigmoid(model(tensor)).item())
    return round(prob, 4)
