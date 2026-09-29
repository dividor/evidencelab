## Content Moderation

The [Content policy](../overview/terms.md#content-policy) in the Terms of Service defines what must not be in the library and how anyone can report it: a one-star rating with the reason in the comment, the floating **Feedback** button for visitors without an account, or email. Reports arrive in **Admin Panel → Ratings** with the triage statuses described under [Ratings & Feedback](../using-evidence-lab/ratings-feedback.md). Filter the queue by a score of 1 and search comments for report keywords such as "illegal", "personal data" or "copyright".

Once a report is upheld, a superuser can **hide the document** from the whole platform in one action. A hidden document:

- disappears from Search, Document Search, title search and facet counts
- is not used by the AI summary, the Research Assistant, Brief research or Map cells
- is not returned by the MCP and A2A servers
- answers `404` on its document, PDF, thumbnail, chunk and highlight endpoints
- stays in the library, marked **hidden** in the Documents Library, so it can be restored

**Hiding from the UI.** Superusers see a **Moderation** column in the Documents Library (Documents tab) with a **Hide** button on every row. Hiding asks for a reason, which is stored with the document and written to the audit log together with the acting administrator; the row then shows a red **hidden** badge and the button becomes **Restore**. Only superusers see hidden documents in the list; for everyone else they are simply absent.

**Hiding from the command line.** Deployments that run without the user module, or operators working on the host, use the same mechanism through a script:

```bash
python scripts/pipeline/hide_document.py --data-source uneg --doc-id 123 --reason "copyright complaint, ticket 42"
python scripts/pipeline/hide_document.py --data-source uneg --doc-id 123 --restore
python scripts/pipeline/hide_document.py --data-source uneg --list
```

**API.** `POST /moderation/documents/{doc_id}/hidden` with `{"hidden": true, "reason": "..."}` (superuser only, user module required) hides or restores; `GET /moderation/documents/hidden` lists hidden documents. Audit events are `document_hidden` and `document_restored`.

**Removing content for good.** Hiding is reversible and immediate. To remove a document permanently, delete it from the source library and re-run the pipeline scan; see [Pipeline Configuration](pipeline-configuration.md).

### Checklist for a report

1. Open **Admin Panel → Ratings**, find the report and set its status to **Acknowledged**.
2. Open the item the reporter saw (the rating's context shows the query and the document).
3. If the content policy is breached, hide the document from the Documents Library (or the CLI) with the report as the reason.
4. Set the report to **Resolved** with a note; if it is not upheld, set **Won't fix** and leave the document visible.
5. For a permanent removal, delete the document from the source library and re-run the pipeline scan.

The Terms commit to acting "promptly on confirmation"; operators are expected to review the queue at least weekly.
