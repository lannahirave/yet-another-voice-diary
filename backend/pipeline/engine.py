"""High-level pipeline engine."""
from ..config import BackendConfig


class PipelineEngine:
    """Main pipeline engine interface."""

    def __init__(self, config: BackendConfig):
        self.config = config
