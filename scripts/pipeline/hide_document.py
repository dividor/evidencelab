"""Hide or restore a document from the command line.

The admin panel offers the same action when the user module is enabled; this
script is for deployments that run without authentication, and for operators
working on the host. Hiding removes the document from search, listings,
facets, the research assistant and the MCP/A2A endpoints while keeping it in
the library. See docs/admin/user-administration.md (Content moderation).

Usage:
    python scripts/pipeline/hide_document.py --data-source uneg --doc-id 123 \
        --reason "copyright complaint, ticket 42"
    python scripts/pipeline/hide_document.py --data-source uneg --doc-id 123 --restore
    python scripts/pipeline/hide_document.py --data-source uneg --list
"""

import argparse
import getpass
import sys

from pipeline.db.database import Database
from pipeline.db.moderation import is_hidden, set_document_hidden


def list_hidden(db: Database) -> int:
    """Print the hidden documents in the data source; returns the count."""
    result = db.pg.get_paginated_documents(
        page=1,
        page_size=200,
        filters={"include_hidden": True, "hidden": True},
        sort_by="last_updated",
        sort_order="desc",
    )
    docs = result.get("documents", [])
    for doc in docs:
        print(
            f"{doc.get('doc_id')}\t{doc.get('map_title') or ''}\t"
            f"{doc.get('sys_hidden_reason') or ''}"
        )
    print(f"{len(docs)} hidden document(s) in {db.data_source}")
    return len(docs)


def set_hidden(db: Database, doc_id: str, hidden: bool, reason: str | None) -> None:
    """Hide or restore one document, refusing unknown ids."""
    doc = db.pg.fetch_docs([doc_id]).get(str(doc_id))
    if not doc:
        raise SystemExit(f"Document {doc_id} not found in {db.data_source}")
    if hidden and is_hidden(doc):
        print(f"Document {doc_id} is already hidden")
        return
    if not hidden and not is_hidden(doc):
        print(f"Document {doc_id} is not hidden")
        return
    set_document_hidden(
        db, doc_id, hidden, reason=reason, actor=f"cli:{getpass.getuser()}"
    )
    print(f"Document {doc_id} {'hidden' if hidden else 'restored'}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data-source", required=True, help="Data source key")
    parser.add_argument("--doc-id", help="Document id to hide or restore")
    parser.add_argument("--reason", help="Why the document is hidden (stored with it)")
    parser.add_argument(
        "--restore", action="store_true", help="Restore instead of hide"
    )
    parser.add_argument("--list", action="store_true", help="List hidden documents")
    args = parser.parse_args(argv)

    if not args.list and not args.doc_id:
        parser.error("--doc-id is required unless --list is given")

    db = Database(data_source=args.data_source)
    if args.list:
        list_hidden(db)
        return
    set_hidden(db, args.doc_id, hidden=not args.restore, reason=args.reason)


if __name__ == "__main__":
    main(sys.argv[1:])
