#!/usr/bin/env python3
import os

from pipeline.db import get_db

db = get_db("uneg")
u = 0
for d in db.get_all_documents():
    fp = d.get("filepath", "")
    di = d.get("id")
    if not fp or not fp.endswith(".pdf"):
        continue
    dx = fp[:-4] + ".docx"
    dc = fp[:-4] + ".doc"
    nf = None
    if os.path.exists("/app/" + dx):
        nf = dx
    elif os.path.exists("/app/" + dc):
        nf = dc
    if nf:
        db.update_document(di, {"filepath": nf, "status": "downloaded"})
        u += 1
        if u % 100 == 0:
            print(f"Progress: {u}")
print(f"Updated {u}")
