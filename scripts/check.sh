#!/usr/bin/env bash

set -euo pipefail

echo "Running Black..."
uv run black --check src tests

echo "Running isort..."
uv run isort --check-only src tests

echo "Running Ruff..."
uv run ruff check src tests

echo "Running mypy..."
uv run mypy src tests

echo "Running tests..."
uv run pytest -v

echo
echo "All tools and tests are passing."
