"""Synchronise the warehouse inventory with the online shop."""

import json
from dataclasses import dataclass


@dataclass
class Item:
    sku: str
    quantity: int


class InventorySync:
    """Pulls stock levels from the warehouse and pushes them to the shop."""

    def __init__(self, warehouse_url: str, shop_url: str) -> None:
        self.warehouse_url = warehouse_url
        self.shop_url = shop_url

    def fetch_items(self, payload: str) -> list[Item]:
        # Parse the warehouse export (JSON list of {sku, quantity}).
        return [Item(entry["sku"], int(entry["quantity"])) for entry in json.loads(payload)]

    def low_stock(self, items: list[Item], threshold: int = 5) -> list[Item]:
        """Items whose quantity is at or below the threshold."""
        return [item for item in items if item.quantity <= threshold]
