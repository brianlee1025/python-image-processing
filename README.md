# image-processing-service

Image processing service for Playbook. It renders shareable cards - a player
namecard, a squad card, an event poster - so a user can post their profile,
squad or game to social media.

playbook-be sends a request on `image-render-requests`, this service draws the
card with Pillow and replies on `image-render-results` with the image as
base64, which the backend hands back to the waiting frontend.

Renders run on a bounded thread pool, and the Kafka consumer pauses its
partitions when that pool is full, so a rush of users queues in Kafka rather
than piling up in memory. See [share_cards.md](./docs/dev/share_cards.md) for
the message contract and the backend/frontend wiring.

Local development uses the Redpanda that already runs in playbook-be's stack;
this service does not start a broker of its own.

```bash
# Setup, once per checkout (or `make install` if you have uv)
py -3.12 -m venv .venv && .venv\Scripts\activate && pip install -e . && cp .env.example .env
```

```bash
# One card, no broker needed
image_processing_service sample-card --kind EVENT --layout STORY --out card.png
```

```bash
# The Kafka worker, no flags: .env has the broker and the storage allow list
python main.py
```

`main.py` is the development shortcut; `image_processing_service render-worker`
is the same thing through the installed console script.

## CLI

```bash
image_processing_service --help
```

## Developer Documentation

Comprehensive developer documentation is available in [`docs/dev/`](./docs/dev/) covering testing, configuration, deployment, and all project features.

### Quick Start for Developers

```bash
# Install development environment
make install

# Start services with Docker
docker compose up -d

# Run tests
make tests

# Auto-fix formatting
make chores
```

See the [developer documentation](./docs/dev/README.md) for complete guides and reference.
