# Humanitarian Evaluation Search UI

Modern TypeScript + React search interface with FastAPI backend for semantic search over humanitarian evaluation documents.

## Features

- ✅ Semantic search with vector embeddings (dense + sparse hybrid)
- ✅ Faceted filtering (organization, year, country, region, evaluation_type, theme)
- ✅ PDF viewer with bounding box highlighting using Docling metadata
- ✅ Dual-mode search: chunks (detailed) or documents (overview)
- ✅ Real-time highlighting with coordinate transformations
- ✅ Responsive design

## Implementation Status

### ✅ Backend Complete (FastAPI)
**Location**: `ui/backend/main.py`

**Endpoints:**
- `GET /search` - Semantic search with filters and faceting
- `GET /facets` - Filter facets with counts
- `GET /document/{doc_id}` - Document metadata
- `GET /pdf/{doc_id}` - Serve PDF files
- `GET /highlight/{doc_id}` - Bounding boxes for highlighting

**Features:**
- ✅ Integrates with Qdrant vector search via `scripts.search.search_chunks()`
- ✅ Document metadata denormalized to chunks (no JOINs)
- ✅ Native Qdrant faceting for fast aggregations
- ✅ Bounding box extraction from Docling JSON
- ✅ CORS enabled for frontend communication

### ✅ Frontend Complete (React + TypeScript)
**Location**: `ui/frontend/`

**Components:**
- ✅ `SearchBox.tsx` - Search input with submit
- ✅ `FacetPanel.tsx` - Filterable facets with counts
- ✅ `ResultsList.tsx` - Search results with metadata
- ✅ `PDFViewer.tsx` - PDF.js viewer with highlight overlays

## Architecture

```
ui/
├── backend/          # FastAPI server
│   ├── main.py      # Search API endpoints
│   └── requirements.txt
└── frontend/        # React + TypeScript
    ├── src/
    │   ├── components/
    │   │   ├── SearchBox.tsx
    │   │   ├── FacetPanel.tsx
    │   │   ├── ResultsList.tsx
    │   │   └── PDFViewer.tsx
    │   ├── types/
    │   │   └── api.ts
    │   ├── App.tsx
    │   └── App.css
    ├── package.json
    └── tsconfig.json
```

## Prerequisites

- Docker and Docker Compose (recommended)
- OR Node.js 18+ and Python 3.11+ (for local development)

## Quick Start (Docker)

### 1. Build and Start Services

From the project root:

```bash
# Start all services (Qdrant, pipeline, backend, frontend)
docker compose up -d

# Backend will be available at: http://localhost:8000
# Frontend will be available at: http://localhost:3000
```

### 2. Access the Search UI

Open your browser to: **http://localhost:3000**

The UI will automatically connect to the backend API at `http://localhost:8000`.

## Local Development

### Backend

```bash
cd ui/backend

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export QDRANT_HOST=localhost  # or 'qdrant' if using Docker


# Run server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Backend will be available at: http://localhost:8000
API Documentation: http://localhost:8000/docs

### Frontend

```bash
cd ui/frontend

# Install dependencies
npm install

# Start development server
npm start
```

Frontend will be available at: http://localhost:3000

## API Endpoints

### Search
```
GET /search?q={query}&limit={num}&organization={org}&year={year}...
```
Semantic search with optional filters. Returns results with facets.

### Facets
```
GET /facets
```
Get all available filter values with document counts.

### Document Metadata
```
GET /document/{doc_id}
```
Get full document metadata.

### PDF Serving
```
GET /pdf/{doc_id}
```
Serve PDF file for viewing.

### Highlights
```
GET /highlight/{doc_id}?page={page}&text={text}
```
Get bounding boxes for highlighting specific text on pages.

## UI Features

### Search Interface
- **Search Box**: Centered search with instant results
- **Auto-complete**: Suggested searches based on indexed content
- **Faceted Filters**: Left sidebar with document counts

### Filter Panel (Left Sidebar)
Collapsible faceted filters with counts:
- Organizations
- Years (range slider)
- Evaluation Types
- Countries (searchable)
- Regions
- Themes

### Results Panel (Center)
Each result shows:
- Document Title (clickable to open PDF)
- Organization badge
- Year, Country, Region, Theme
- Page number and relevance score
- Text snippet with query highlighted
- Breadcrumb: Section headings from TOC

### PDF Viewer (Overlay Panel)
- Opens as overlay when clicking a result
- PDF.js-based viewer with:
  - Yellow highlight overlays on matching text
  - Bounding boxes from Docling JSON
  - Coordinate transformation (bottom-left → top-left)
  - Navigation: Page controls
  - Zoom controls
  - Direct page jump

## Configuration

### Backend (`backend/main.py`)

Configure CORS origins for production:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],  # Update for production
    ...
)
```

### Frontend (`frontend/.env`)

```bash
REACT_APP_API_URL=http://localhost:8000
```

## Building for Production

### Backend
```bash
cd ui/backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Frontend
```bash
cd ui/frontend
npm run build
# Serve the build/ directory with nginx or similar
```

## Troubleshooting

### Backend can't connect to Qdrant
```bash
# Check Qdrant is running
docker compose ps qdrant

# Check connection
curl http://localhost:6333/collections
```

### Frontend can't reach backend
```bash
# Check backend is running
curl http://localhost:8000/health

# Check CORS configuration in backend/main.py
```

### No search results
```bash
# Verify documents are indexed
docker compose exec pipeline python scripts/status.py

# Index documents if needed
docker compose exec pipeline python pipeline/index.py
```

### PDF viewer not loading
- Ensure PDFs exist in `data/pdfs/` directory
- Check file paths in Qdrant documents collection
- Verify PDF is accessible via `/pdf/{doc_id}` endpoint
- Check browser console for errors

### Highlights not appearing
- Verify chunks have `bbox` data in Qdrant
- Check coordinate transformation logic in `PDFViewer.tsx`
- Ensure bounding boxes are in correct format: `{l, b, r, t}`

## Development Notes

### Adding New Filters

1. Update `SearchFilters` interface in `frontend/src/types/api.ts`
2. Add query parameter to `/search` endpoint in `backend/main.py`
3. Add filter UI in `FacetPanel.tsx`
4. Update facets calculation in `/facets` endpoint

### Customizing Highlights

Highlight colors and styles in `PDFViewer.tsx`:
```css
.highlight-overlay {
    background: rgba(255, 235, 59, 0.4);  /* Yellow with 40% opacity */
    border: 2px solid rgba(255, 193, 7, 0.8);
}
```

### Performance Optimization

- Backend caches embedding models after first use
- Frontend uses React.memo for expensive components
- Pagination: Set reasonable `limit` parameter (default: 50)
- Facets use native Qdrant aggregation (fast even with large collections)

## License

MIT License - See main project LICENSE file
