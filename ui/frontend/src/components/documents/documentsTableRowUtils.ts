export const getFormatLabel = (fileFormat?: string): string => {
  if (fileFormat === 'pdf') {
    return '📄 PDF';
  }
  if (fileFormat === 'docx') {
    return '📝 DOCX';
  }
  return fileFormat ? fileFormat.toUpperCase() : '-';
};

export const buildErrorText = (doc: any): string => {
  const parts: string[] = [];
  if (doc.error) {
    parts.push(doc.error);
  }
  if (doc.message) {
    parts.push(doc.message);
  }
  if (parts.length > 0) {
    return parts.join(' - ');
  }
  return doc.error_message || doc.download_error || '-';
};
