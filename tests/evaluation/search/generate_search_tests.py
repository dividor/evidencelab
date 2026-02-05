import argparse
import glob
import json
import math
import os
import random
import re
import sys
from collections import Counter
from pathlib import Path

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from dotenv import load_dotenv  # noqa: E402
from jinja2 import Environment, FileSystemLoader  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402

from utils.llm_factory import get_llm  # noqa: E402

load_dotenv()

# Setup Jinja2
PROMPTS_DIR = Path(__file__).parent.parent.parent.parent / "prompts"
jinja_env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)))

# Load templates
tmpl_question = jinja_env.get_template("search_tests_generate_question_user.j2")
tmpl_keywords = jinja_env.get_template("search_tests_generate_keywords_user.j2")
tmpl_verify = jinja_env.get_template("search_tests_verify_relevance_user.j2")


def load_chunk_file(filepath):
    """Load a chunks.json file."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Failed to load {filepath}: {e}")
        return []


def load_metadata_for_chunk_file(chunk_filepath):
    """
    Attempt to find the corresponding metadata JSON for a chunks.json file.
    Assumes structure:
    Chunks:   data/DOC_SOURCE/parsed/AGENCY/YEAR/DOC_NAME/chunks/chunks.json
    Metadata: data/DOC_SOURCE/pdfs/AGENCY/YEAR/DOC_NAME.json
    """
    try:
        path = Path(chunk_filepath)
        # Check if we are in a 'chunks' subdir of a 'parsed' tree
        # path parts example:
        # ('data', 'uneg', 'parsed', 'UNDESA', '2023', 'DOC_NAME', 'chunks', 'chunks.json')

        parts = list(path.parts)

        if "parsed" in parts and "chunks" in parts:
            # Find index of 'parsed'
            parsed_idx = parts.index("parsed")
            # Replace 'parsed' with 'pdfs'
            parts[parsed_idx] = "pdfs"

            # The doc name directory should be the parent of 'chunks'
            # (parts[-2] is 'chunks', parts[-3] is DOC_NAME_DIR)

            # We want to form: .../pdfs/AGENCY/YEAR/DOC_NAME.json
            # Currently parts point to .../pdfs/.../DOC_NAME/chunks/chunks.json

            # Remove 'chunks' and 'chunks.json' (last 2 parts)
            base_dir_parts = parts[:-2]

            # The last part of base_dir_parts is the DOC_NAME directory.
            # We want that to be a .json file instead.
            doc_name = base_dir_parts[-1]
            parent_dir = Path(*base_dir_parts[:-1])  # everything up to YEAR

            metadata_path = parent_dir / f"{doc_name}.json"

            if metadata_path.exists():
                with open(metadata_path, "r", encoding="utf-8") as f:
                    return json.load(f)

        return {}
    except Exception as e:
        print(f"Warning: Failed to load metadata for {chunk_filepath}: {e}")
        return {}


def simple_tokenize(text):
    """Simple tokenizer for basic search ranking."""
    # Lowercase and remove non-alphanumeric chars
    text = re.sub(r"[^\w\s]", "", text.lower())
    return text.split()


class BM25Index:
    def __init__(self, chunks):
        self.chunks = chunks
        self.doc_count = len(chunks)
        self.avg_doc_len = 0
        self.doc_freqs = []
        self.idf = {}
        self.doc_len = []
        self.chunk_tokens = []

        self._build_index()

    def _build_index(self):
        total_len = 0
        df = Counter()

        for chunk in self.chunks:
            tokens = simple_tokenize(chunk["text"])
            self.chunk_tokens.append(tokens)
            self.doc_len.append(len(tokens))
            total_len += len(tokens)

            # Count unique tokens in this doc for DF
            unique_tokens = set(tokens)
            for t in unique_tokens:
                df[t] += 1

        self.avg_doc_len = total_len / self.doc_count if self.doc_count > 0 else 0

        # Calc IDF
        for token, freq in df.items():
            # IDF = log( (N - n + 0.5) / (n + 0.5) + 1 )
            self.idf[token] = math.log((self.doc_count - freq + 0.5) / (freq + 0.5) + 1)

    def score(self, query_tokens, top_k=10, k1=1.5, b=0.75):
        scores = []

        for i, doc_tokens in enumerate(self.chunk_tokens):
            score = 0.0
            doc_len = self.doc_len[i]

            # Frequency of query term in doc
            doc_token_counts = Counter(doc_tokens)

            for qt in query_tokens:
                if qt not in self.idf:
                    continue

                idf = self.idf[qt]
                freq = doc_token_counts[qt]

                # BM25 formula
                numerator = freq * (k1 + 1)
                denominator = freq + k1 * (1 - b + b * (doc_len / self.avg_doc_len))
                score += idf * (numerator / denominator)

            if score > 0:
                scores.append((score, self.chunks[i]))

        # Sort desc
        scores.sort(key=lambda x: x[0], reverse=True)
        return [c for s, c in scores[:top_k]]


def call_llm(llm, template, **kwargs):
    """Helper to render template and call LLM."""
    try:
        content = template.render(**kwargs)
        messages = [HumanMessage(content=content)]
        # Add timeout/retry logic internally to LLM or here if needed, but simple for now
        response = llm.invoke(messages)

        if hasattr(response, "content"):
            return response.content.strip()
        else:
            return str(response).strip()
    except Exception as e:
        print(f"LLM Call Error: {e}")
        return None


def generate_question(llm, chunk_text, instructions):
    return call_llm(
        llm, tmpl_question, chunk_text=chunk_text, instructions=instructions
    )


def generate_keywords(llm, question):
    resp = call_llm(llm, tmpl_keywords, question=question)
    if not resp:
        return []
    # Parse JSON
    try:
        # cleanup markdown code blocks if present
        if "```" in resp:
            resp = resp.split("```")[1]
            if resp.startswith("json"):
                resp = resp[4:]
        return json.loads(resp)
    except Exception as e:
        print(f"Failed to parse keywords JSON: {resp} | Error: {e}")
        return []


def verify_relevance(llm, question, chunk_text):
    resp = call_llm(llm, tmpl_verify, question=question, chunk_text=chunk_text)
    if not resp:
        return False
    return "YES" in resp.upper()


def generate_tests(data_dir, num_docs, num_queries, output_file, instructions):
    print("Initializing LLM...")
    try:
        llm = get_llm(temperature=0.7)
    except Exception as e:
        print(f"Failed to initialize LLM: {e}")
        return

    print("Scanning for data...")
    files = glob.glob(os.path.join(data_dir, "**", "chunks.json"), recursive=True)
    if not files:
        print("No data found.")
        return

    # To ensure good search, we need a decent corpus size, but we only sample
    # questions from a subset.
    # Let's load chunks from the requested num_docs files to serve as questions,
    # PLUS maybe some noise? For now, we just use the loaded subset as BOTH the source of questions
    # AND the search index.

    sampled_files = random.sample(files, min(num_docs, len(files)))
    all_chunks = []

    print(f"Loading chunks and metadata from {len(sampled_files)} files...")

    for fp in sampled_files:
        chunks = load_chunk_file(fp)
        metadata = load_metadata_for_chunk_file(fp)

        doc_title = metadata.get("title", "Unknown Title")
        doc_filename = metadata.get("filename", Path(fp).name)  # fallback
        # doc_id is usually a hash or provided field.
        # If not present in metadata, we can use the chunk's doc_id if available, or generate one.
        # chunks usually have 'doc_id'.

        for chunk in chunks:
            if "text" in chunk and len(chunk["text"]) > 100:
                chunk["_source_file"] = fp
                chunk["_title"] = doc_title
                chunk["_filename"] = doc_filename

                # In chunks.json, there is usually "doc_id".
                # If not, use filename as ID
                if "doc_id" not in chunk:
                    chunk["doc_id"] = doc_filename

                all_chunks.append(chunk)

    print(f"Loaded {len(all_chunks)} valid chunks.")
    if not all_chunks:
        return

    # Build BM25 Index
    print("Building BM25 Index...")
    search_index = BM25Index(all_chunks)

    # Shuffle for source selection
    source_pool = all_chunks[:]
    random.shuffle(source_pool)

    test_cases = []
    generated_count = 0

    # Iterate through chunks to generate source questions
    for source_chunk in source_pool:
        if generated_count >= num_queries:
            break

        print(f"Processing Query {generated_count + 1}/{num_queries}...")

        # 1. Generate Question
        question = generate_question(llm, source_chunk["text"], instructions)
        if not question:
            continue
        print(f"  Question: {question}")

        # 2. Generate Keywords
        keywords = generate_keywords(llm, question)
        if not keywords:
            print("  Failed to extract keywords.")
            continue
        print(f"  Keywords: {keywords}")

        # 3. Search Candidates via BM25
        search_query_tokens = []
        for kw in keywords:
            search_query_tokens.extend(simple_tokenize(kw))

        candidates = search_index.score(search_query_tokens, top_k=10)
        print(f"  Found {len(candidates)} candidates via BM25.")

        # 4. Verify Relevance
        verified_results = []
        for cand in candidates:
            # check relevance
            is_relevant = verify_relevance(llm, question, cand["text"])

            if is_relevant:
                is_source = cand["text"] == source_chunk["text"]
                verified_results.append(
                    {
                        "file": str(cand["_filename"]),  # Use filename as requested
                        "title": str(cand["_title"]),
                        "page": cand.get("page_num"),
                        "id": str(cand.get("doc_id")),  # Document ID
                        "snippet": cand["text"],
                        "relevance": "primary_source" if is_source else "relevant",
                    }
                )

        print(f"  Verified {len(verified_results)} relevant chunks.")

        if not verified_results:
            print("  No candidates verified as relevant. Skipping.")
            continue

        test_cases.append(
            {
                "query": question,
                "keywords": keywords,
                "expected_count": len(verified_results),
                "expected_results": verified_results,
            }
        )
        generated_count += 1

    # Save
    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    existing_tests = []
    if out_path.exists():
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                existing_tests = json.load(f)
                if not isinstance(existing_tests, list):
                    print(f"Warning: {out_path} is not a list. Overwriting.")
                    existing_tests = []
        except Exception as e:
            print(f"Warning: Failed to load existing tests from {out_path}: {e}")
            existing_tests = []

    all_tests = existing_tests + test_cases

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_tests, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(test_cases)} new tests to {out_path} (Total: {len(all_tests)})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="./data")
    parser.add_argument("--num-docs", type=int, default=10)
    parser.add_argument("--num-queries", type=int, default=5)
    parser.add_argument(
        "--output", default="tests/evaluation/search/search_test_dataset.json"
    )
    parser.add_argument(
        "--instructions",
        default=(
            "generate general humanitarian questions a person might ask of humanitarian reports"
        ),
    )

    args = parser.parse_args()
    generate_tests(
        args.data_dir, args.num_docs, args.num_queries, args.output, args.instructions
    )
