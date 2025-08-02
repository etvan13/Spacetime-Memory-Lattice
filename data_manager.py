import os
import json
import shutil
from typing import Dict, List, Optional
from block_data import BlockData


class DataManager:
    """
    Stores / retrieves BlockData objects inside a 60⁶ coordinate space.

    Directory strategy (revised):
        …/coordinate_data/{c1}/{c2}/{c3}/{c4}/{c5}.json
    where the full coordinate is "c6 c5 c4 c3 c2 c1".
    We nest by the *last four* digits (c1 → c4),
    use the *second* digit (c5) as the JSON filename,
    and store each block under the key "c6 c5 c4 c3 c2 c1".

    Attachments for each coordinate are stored in:
        …/coordinate_data/{c1}/{c2}/{c3}/{c4}/attachments/{full_key}/
    """

    # ── Init ────────────────────────────────────────────────────────────────
    def __init__(
        self,
        base_dir: Optional[str] = None,
        attachments_source_dir: Optional[str] = None
    ) -> None:
        self.base_dir = (
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "../data")
            if base_dir is None else base_dir
        )
        self.attachments_source_dir = attachments_source_dir

        self.coordinate_dir = os.path.join(self.base_dir, "data")
        os.makedirs(self.coordinate_dir, exist_ok=True)

    # ── Private helpers ───────────────────────────────────────────────────────
    def _paths(self, coordinate: str) -> tuple[str, str, str, List[str]]:
        """
        Returns:
            json_path – path to .../c1/c2/c3/c4/c5.json
            full_key  – the full "c6 c5 c4 c3 c2 c1" string
            dir_path  – the directory .../c1/c2/c3/c4
            parts     – list of the 6 coordinate parts
        """
        parts = coordinate.split()
        if len(parts) != 6:
            raise ValueError("Coordinate must have exactly 6 parts.")

        c6, c5, c4, c3, c2, c1 = parts
        dir_path = os.path.join(self.coordinate_dir, c1, c2, c3, c4)
        json_path = os.path.join(dir_path, f"{c5}.json")
        full_key = " ".join(parts)
        return json_path, full_key, dir_path, parts

    @staticmethod
    def _load_json(path: str) -> Dict:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                try:
                    return json.load(f)
                except json.JSONDecodeError:
                    print(f"⚠  {path} is corrupted – re-initialising.")
        return {}

    @staticmethod
    def _write_json(path: str, data: Dict) -> None:
        # Sort only the outermost keys (the coordinate keys)
        ordered = dict(sorted(data.items(), key=lambda x: x[0]))

        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(ordered, f, indent=4)

    # ── Core API ──────────────────────────────────────────────────────────────
    def create_coordinate_block(self, coordinate: str, block: BlockData) -> None:
        """
        Stores the block under its full_key in the JSON file,
        and copies attachments to the per-coordinate attachments folder.
        """
        json_path, full_key, dir_path, _ = self._paths(coordinate)
        os.makedirs(dir_path, exist_ok=True)

        # ── Attachments ─────────────────────────────────────────────────────
        if self.attachments_source_dir and getattr(block, "attachments", None):
            # new: replace spaces with dashes for filesystem-safe folder names
            sanitized_key = full_key.replace(" ", "-")
            att_dir = os.path.join(dir_path, "attachments", sanitized_key)
            os.makedirs(att_dir, exist_ok=True)
            for fname in block.attachments:
                src = os.path.join(self.attachments_source_dir, fname)
                dst = os.path.join(att_dir, fname)
                if os.path.exists(src) and not os.path.exists(dst):
                    shutil.copy2(src, dst)
                elif not os.path.exists(src):
                    print(f"⚠  Attachment not found: {src}")

        # ── Load existing data & append this block ───────────────────────────
        data = self._load_json(json_path)
        buckets = data.setdefault(full_key, [])

        # Prevent duplicate universes
        existing = [b.get("universe") for b in buckets]
        if block.universe in existing:
            block.universe = (max(existing) + 1) if existing else 0

        buckets.append(block.to_dict())
        buckets.sort(key=lambda b: b.get("universe"))

        self._write_json(json_path, data)

    # ── Convenience wrappers ──────────────────────────────────────────────────
    def load_coordinate_data(self, coordinate: str) -> List[Dict]:
        json_path, full_key, _, _ = self._paths(coordinate)
        data = self._load_json(json_path)
        return data.get(full_key, [])

    def save_coordinate_data(self, coordinate: str, blocks: List[Dict]) -> None:
        json_path, full_key, dir_path, _ = self._paths(coordinate)
        os.makedirs(dir_path, exist_ok=True)
        data = self._load_json(json_path)
        data[full_key] = blocks
        self._write_json(json_path, data)

    def coordinate_exists(self, coordinate: str) -> bool:
        return bool(self.load_coordinate_data(coordinate))

    # ── Layer utilities ──────────────────────────────────────────────────────
    def add_layer_to_coordinate(self, coordinate: str, layer_data: Dict) -> None:
        data = self.load_coordinate_data(coordinate)
        data.append(layer_data)
        self.save_coordinate_data(coordinate, data)

    def add_layer_to_universe(
        self, coordinate: str, universe: int, layer_level: int, layer_data: Dict
    ) -> None:
        data = self.load_coordinate_data(coordinate)
        for block in data:
            if block.get("universe") == universe:
                block.setdefault("layers", {})[str(layer_level)] = layer_data
                self.save_coordinate_data(coordinate, data)
                return
        print(f"No universe {universe} at {coordinate} – layer not added.")

    def get_layer_data_for_coordinate(self, coordinate: str, layer: int) -> Optional[Dict]:
        for block in self.load_coordinate_data(coordinate):
            if str(layer) in block.get("layers", {}):
                return block["layers"][str(layer)]
        return None

    def get_layer_data_for_universe(
        self, coordinate: str, universe: int, layer: int
    ) -> Optional[Dict]:
        for block in self.load_coordinate_data(coordinate):
            if block.get("universe") == universe:
                return block.get("layers", {}).get(str(layer))
        return None
