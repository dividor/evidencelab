# Use shared base image with all dependencies pre-installed
FROM evidencelab-ai-base:latest

# Copy project files
COPY . /app/

WORKDIR /app/ui/backend

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
