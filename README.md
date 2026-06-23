# Chat Buddy

A conversational AI application for interacting with local LLMs through a persistent chat interface.

![Python Version from PEP 621 TOML](https://img.shields.io/python/required-version-toml?tomlFilePath=https://github.com/babaksoft/chat-buddy/raw/refs/heads/master/pyproject.toml)
![Static Badge](https://img.shields.io/badge/category-gen_ai-orange)
![Static Badge](https://img.shields.io/badge/framework-llama_index-orange)
![GitHub License](https://img.shields.io/github/license/babaksoft/chat-buddy)
![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/babaksoft/chat-buddy/ci.yml)


## Goals

- Persistent conversations
- Conversation resume support
- Context window management
- Local-first deployment
- Observability and monitoring

## Technology Stack

- Python 3.12
- Streamlit
- Ollama
- PostgreSQL
- SQLAlchemy
- Alembic
- LlamaIndex
- Arize Phoenix
- Prometheus
- Grafana

## Architecture

UI (Streamlit)
    ↓
Application Services
    ↓
LLM Gateway + Repository
    ↓
Ollama + PostgreSQL

## Development Status

- [x] Logging
- [x] Database Connectivity
- [x] ORM Models
- [x] Alembic Migrations
- [x] Repository Layer
- [ ] Application Services
- [ ] Ollama Integration
- [ ] Streamlit Chat UI
- [ ] Context Management
- [ ] Evaluation Framework
- [ ] Monitoring Dashboard

## Running Tests

pytest
