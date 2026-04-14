"""Model loading, versioning, health checks, and retrain orchestration."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path("data/models")


class ModelManager:
    """Central manager for ML model files and metadata.

    Handles model persistence in ``data/models/``, tracks version
    metadata in ``model_meta.json``, and orchestrates nightly retraining
    by delegating to registered learners.
    """

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self._data_dir = data_dir or DEFAULT_DATA_DIR
        self._meta: dict[str, Any] = {}
        self._models: dict[str, Any] = {}
        self._learners: list[Any] = []

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def load_all(self) -> None:
        """Create the models directory and load metadata + any existing models."""
        self._data_dir.mkdir(parents=True, exist_ok=True)

        meta_path = self._data_dir / "model_meta.json"
        if meta_path.exists():
            try:
                self._meta = json.loads(meta_path.read_text(encoding="utf-8"))
                logger.info(
                    "Loaded model metadata: %d model(s) tracked",
                    len(self._meta),
                )
            except Exception as exc:
                logger.error("Failed to load model_meta.json: %s", exc)
                self._meta = {}
        else:
            logger.info("No model_meta.json found — starting fresh")

        # Load any persisted model files that exist
        for name, info in self._meta.items():
            file_name = info.get("file")
            if file_name:
                path = self._data_dir / file_name
                if path.exists():
                    try:
                        self._models[name] = self._load_file(path)
                        logger.info("Loaded model '%s' from %s", name, path.name)
                    except Exception as exc:
                        logger.warning("Failed to load model '%s': %s", name, exc)
                else:
                    logger.warning("Model file missing for '%s': %s", name, path)

    def _load_file(self, path: Path) -> Any:
        """Load a model file based on its extension."""
        if path.suffix == ".json":
            return json.loads(path.read_text(encoding="utf-8"))
        # Binary model files (e.g. .lgb) loaded by their respective services
        return path

    # ------------------------------------------------------------------
    # Model CRUD
    # ------------------------------------------------------------------

    def get_model(self, name: str) -> Optional[Any]:
        """Return a loaded model by name, or None if not available."""
        return self._models.get(name)

    def save_model(
        self,
        name: str,
        data: Any,
        *,
        file_name: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        """Persist a model to disk and update metadata.

        Args:
            name: Logical model name (e.g. ``lighting_prefs``).
            data: Model data — dict for JSON models, or raw bytes.
            file_name: File name within ``data/models/``.  Defaults to
                ``{name}.json`` for dicts.
            metadata: Extra fields to store in ``model_meta.json``.
        """
        if file_name is None:
            file_name = f"{name}.json"

        path = self._data_dir / file_name
        if isinstance(data, dict):
            path.write_text(
                json.dumps(data, indent=2, default=str),
                encoding="utf-8",
            )
        elif isinstance(data, (bytes, bytearray)):
            path.write_bytes(data)
        else:
            # Assume it's a path-like or string — caller handles persistence
            pass

        self._models[name] = data
        self._meta[name] = {
            "file": file_name,
            "version": datetime.now(timezone.utc).isoformat(),
            "status": "active",
            **(metadata or {}),
        }
        self._save_meta()
        logger.info("Saved model '%s' → %s", name, path)

    def _save_meta(self) -> None:
        """Write model_meta.json to disk."""
        meta_path = self._data_dir / "model_meta.json"
        meta_path.write_text(
            json.dumps(self._meta, indent=2, default=str),
            encoding="utf-8",
        )

    def update_meta(self, name: str, **kwargs: Any) -> None:
        """Update metadata fields for a model without re-saving the model file."""
        if name in self._meta:
            self._meta[name].update(kwargs)
            self._save_meta()

    def delete_model(self, name: str) -> None:
        """Remove a model's file and metadata."""
        info = self._meta.pop(name, None)
        self._models.pop(name, None)
        if info and info.get("file"):
            path = self._data_dir / info["file"]
            if path.exists():
                path.unlink()
                logger.info("Deleted model file: %s", path)
        self._save_meta()

    # ------------------------------------------------------------------
    # Health & status
    # ------------------------------------------------------------------

    def get_health(self) -> dict[str, Any]:
        """Return per-model status for the /api/learning/status endpoint."""
        health: dict[str, Any] = {}
        for name, info in self._meta.items():
            health[name] = {
                "status": info.get("status", "unknown"),
                "version": info.get("version"),
                "loaded": name in self._models,
                **{
                    k: v
                    for k, v in info.items()
                    if k not in ("file", "status", "version")
                },
            }
        return health

    # ------------------------------------------------------------------
    # Learner registration & retraining
    # ------------------------------------------------------------------

    def register_learner(self, learner: Any) -> None:
        """Register a learner whose ``retrain`` method is called nightly."""
        self._learners.append(learner)
        logger.info("Registered ML learner: %s", type(learner).__name__)

    async def retrain_all(self) -> None:
        """Retrain all registered learners.  Called by the scheduler at 4 AM."""
        logger.info("Starting nightly ML retrain for %d learner(s)", len(self._learners))
        for learner in self._learners:
            try:
                await learner.retrain()
                logger.info("Retrained %s", type(learner).__name__)
            except Exception as exc:
                logger.error(
                    "Retrain failed for %s: %s",
                    type(learner).__name__,
                    exc,
                    exc_info=True,
                )
        logger.info("Nightly ML retrain complete")
