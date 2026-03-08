/**
 * Copies docs from the project root ./docs/ folder into ui/frontend/public/docs/
 * so they are served by the React dev server and included in production builds.
 *
 * Looks for docs in two locations (for Docker build compatibility):
 *   1. ../../docs/  (local dev - relative to ui/frontend/)
 *   2. ./docs_source/  (Docker build - copied by Dockerfile)
 */
const fs = require('fs');
const path = require('path');

const frontendDir = path.resolve(__dirname, '..');
const targetDir = path.join(frontendDir, 'public', 'docs');

// Try local dev path first, then Docker path
const localDocsDir = path.resolve(frontendDir, '..', '..', 'docs');
const dockerDocsDir = path.resolve(frontendDir, 'docs_source');

let sourceDir;
if (fs.existsSync(localDocsDir)) {
  sourceDir = localDocsDir;
} else if (fs.existsSync(dockerDocsDir)) {
  sourceDir = dockerDocsDir;
} else {
  console.warn('[copy-docs] No docs directory found, skipping copy.');
  process.exit(0);
}

function copyRecursive(src, dest) {
  if (!fs.existsSync(dest)) {
    fs.mkdirSync(dest, { recursive: true });
  }

  const entries = fs.readdirSync(src, { withFileTypes: true });
  for (const entry of entries) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);

    if (entry.isDirectory()) {
      copyRecursive(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

// Clean target and copy fresh
if (fs.existsSync(targetDir)) {
  fs.rmSync(targetDir, { recursive: true });
}

copyRecursive(sourceDir, targetDir);

const fileCount = countFiles(targetDir);
console.log(`[copy-docs] Copied ${fileCount} files from ${sourceDir} to ${targetDir}`);

function countFiles(dir) {
  let count = 0;
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    if (entry.isDirectory()) {
      count += countFiles(path.join(dir, entry.name));
    } else {
      count++;
    }
  }
  return count;
}
