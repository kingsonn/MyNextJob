"""Load a catalog from a generated dataset."""

from generator.dataset import Dataset
from services.catalog.store import Catalog
from services.knowledge.retrieve import SourceDocument


def catalog_from_dataset(dataset: Dataset) -> Catalog:
    documents = [
        SourceDocument(document_id=item.document_id, sidecar=item.sidecar)
        for item in dataset.documents
    ]
    return Catalog(dataset.tables(), documents)
