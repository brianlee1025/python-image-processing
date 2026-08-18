# Share Cards

Renders shareable images - a player namecard, a squad card, an event poster -
that a user can post to Instagram, WhatsApp or anywhere else. playbook-be asks
over Kafka, this service draws the card with Pillow and replies with the image
as base64.

```
                    image-render-requests
  playbook-be  ────────────────────────────────►  bridge ──► render pool (N threads)
       ▲                                            │              │
       │            image-render-results            │              │
       └────────────────────────────────────────────┴──────────────┘
```

The user waits on the frontend while this happens, so the whole path is built
around a bounded queue: a card takes 100-250 ms of CPU, and a service that
accepts unlimited work would simply time everyone out at once.

## Topics

| Topic                   | Direction        | Key         | Payload         |
| ----------------------- | ---------------- | ----------- | --------------- |
| `image-render-requests` | be → renderer    | `requestId` | `RenderRequest` |
| `image-render-results`  | renderer → be    | `requestId` | `RenderResult`  |

Both are configurable (`KAFKA_REQUEST_TOPIC`, `KAFKA_RESULT_TOPIC`), and a
request can override where its own answer goes with `replyTopic`.

## Request

```json
{
  "requestId": "0f1c1a24-2b7c-4e0e-8d2b-4d0f2a5a4b90",
  "kind": "USER",
  "layout": "POSTER",
  "format": "AUTO",
  "theme": "midnight",
  "replyTopic": null,
  "payload": {
    "title": "Aisyah Rahman",
    "subtitle": "@aisyahplays",
    "description": "Weekend striker, weekday physio.",
    "location": "Kuala Lumpur, MY",
    "shareUrl": "https://playbookapp.org/profile/v83bYqnxOH",
    "avatarBase64": "iVBORw0KGgoAAAANSUhEUg...",
    "level": 12,
    "sports": ["Football", "Padel"],
    "badges": ["MVP x4", "100 Games"],
    "stats": [
      { "label": "Matches", "value": "128" },
      { "label": "Squads", "value": "6" },
      { "label": "Win rate", "value": "64%" }
    ]
  }
}
```

| Field       | Required | Notes                                                                    |
| ----------- | -------- | ------------------------------------------------------------------------ |
| `requestId` | no       | Defaults to a UUID. Use your own: it is the key you match the reply on.   |
| `kind`      | yes      | `USER`, `SQUAD` or `EVENT`. Decides which payload fields are read.        |
| `layout`    | no       | `POSTER` 1080x1350 (default), `STORY` 1080x1920, `CARD` 1200x630.         |
| `format`    | no       | `AUTO` (default), `PNG`, `JPEG`, `WEBP`. See [Size budget](#size-budget). |
| `theme`     | no       | `midnight`, `turf`, `sunset`, `court`, `ocean`. Unknown names fall back.  |
| `replyTopic`| no       | Overrides the result topic for this request.                             |
| `payload`   | yes      | The card content, below.                                                 |

### Payload

Shared by every kind: `title` (required), `subtitle`, `description`,
`location`, `shareUrl`, `avatarBase64`, `avatarUrl`, `coverBase64`,
`coverUrl`, `stats` (max 4), `badges` (max 4), `accentColor`, `footerNote`,
`ctaLabel`, `actions[]` (max 3).

| Kind    | Extra fields                                                                                                              |
| ------- | ------------------------------------------------------------------------------------------------------------------------- |
| `USER`  | `handle`, `level`, `sports[]`, `verified`, `statusLabel`                                                                   |
| `SQUAD` | `sport`, `memberCount`, `privacy`, `language`, `foundedYear`, `captainName`, `memberAvatarsBase64[]`, `memberAvatarUrls[]` |
| `EVENT` | `sport`, `startsAt`, `endsAt`, `venue`, `hostName`, `squadName`, `spotsLeft`, `priceLabel`, `formatLabel`, `audienceLabel` |

Notes:

- `shareUrl` is printed under the QR code **and** encoded into it. Pass a short
  share link from `ShareLinks` (`/s/`, `/u/`, `/e/`), not a raw database id: a
  shorter payload is a coarser code, and the printed URL has to be readable off
  a phone screen.
- `startsAt` is rendered in whatever UTC offset you send, without conversion.
  Send the event's local time (`2026-09-12T19:30:00+08:00`).
- `stats` drive the detail panel. Each entry may name an `icon`; without one the
  renderer infers a pictogram from the label ("Members" gets two figures,
  "Duration" a clock), so the backend does not have to know the icon set.
- `level` draws a tier coloured "LV 12" badge beside the handle and tints the
  avatar ring to match, mirroring `tier.constant.ts` in playbook-web (rare at 3,
  epic at 6, unique at 10, legendary at 15). A `Level` entry in `stats` is
  dropped when the badge is drawn rather than printing the number twice.
- `verified` draws the tick beside the display name. It is the identity check,
  not email verification: playbook-be sends `user.isIdentityVerified()`.
- `ctaLabel` overrides "SCAN TO JOIN THE SQUAD" and friends. `actions` adds a
  muted row of affordances under the link; there is **no default**, because on a
  flat image "Add to calendar" is a caption for a control that is not there.
  Cards end on their link unless a caller asks for the row.
- Missing avatar? The renderer draws initials in the theme accent instead.
- Missing squad or event banner? It generates one - see [Cover art](#cover-art).
- Unknown fields are ignored, so the backend can add keys without waiting for a
  renderer deploy. Long strings are clipped, not rejected.

### What the cards look like

Three layouts, not one template drawn three times: they answer different
questions, and a shared grid made all three read like a form.

| Kind    | Hero                                        | Detail panel                                | Call to action           |
| ------- | ------------------------------------------- | ------------------------------------------- | ------------------------ |
| `SQUAD` | Banner, badge, name, tagline, sport/privacy | Members, founded, captain, member faces     | "Scan to join the squad" |
| `USER`  | Face, name, tick, handle, level, sports     | XP, squads and whatever else was sent       | "Scan to view profile"   |
| `EVENT` | Banner, host, squad                         | When / where / format, then going and spots | "Scan to join the event" |

Common to all three: a rounded card on a darker page with an accent outline,
the brand mark and kind pill on the top row, and a floor block holding the call
to action, the QR plate and the link.

Text that will not fit is clipped, not wrapped past the edge: a venue gets as
much of the panel column as the column has, then an ellipsis. A full postal
address is wider than half a card.

The pictograms next to venues, times and sports are vector drawn
(`render/icons.py`), not text. System fonts render emoji as tofu boxes, and an
emoji font costs more megabytes than this whole service. `sport_icon` matches on
a substring, so "Beach volleyball" and "5-a-side football" both land somewhere
sensible and anything unrecognised falls back to a ball.

### Cover art

Squad and event cards have a banner across the top. Most squads never upload
one, so when the payload has no `coverUrl` / `coverBase64` the renderer draws a
stand in from the theme and the sport - a tinted wash, angled bands and a large
submerged pictogram - rather than leaving an empty edge. Player cards have no
banner at all: on a namecard the face is the hero.

To use real photography instead, drop files into
`image_processing_service/static/covers` or point `RENDER_DEFAULT_COVER_DIR` at
a directory. Files are matched most specific first:

```
squad-football.jpg  ->  squad.jpg  ->  football.jpg  ->  cover.jpg
```

A file that will not open is logged and skipped, not fatal.

### Imagery

Two ways in: inline `avatarBase64` / `coverBase64` (with or without a
`data:image/png;base64,` prefix), or `avatarUrl` / `coverUrl`.

Remote URLs are refused unless you opt in, because fetching arbitrary URLs
would make this service an SSRF proxy. **playbook-be sends presigned MinIO/S3
links**, so a deployment that talks to the backend needs:

```bash
RENDER_ALLOW_REMOTE_IMAGES=true
RENDER_REMOTE_IMAGE_HOSTS='["minio", "localhost"]'   # your storage hosts
```

Imagery that cannot be loaded - bad base64, an expired link, a host that is not
allow listed, storage being down - costs the user their photo, not their card:
the renderer logs a warning and falls back to generated initials or a plain
gradient. Set `RENDER_STRICT_IMAGES=true` to make those requests fail instead,
which is useful while debugging a storage change.

## Result

```json
{
  "requestId": "0f1c1a24-2b7c-4e0e-8d2b-4d0f2a5a4b90",
  "status": "COMPLETED",
  "kind": "USER",
  "layout": "POSTER",
  "imageBase64": "iVBORw0KGgoAAAANSUhEUgAABDgAAA...",
  "contentType": "image/png",
  "width": 1080,
  "height": 1350,
  "byteSize": 132951,
  "renderMs": 118,
  "queuedMs": 3,
  "error": null,
  "completedAt": "2026-08-17T09:12:44.221Z"
}
```

`status` is `COMPLETED`, `FAILED` or `REJECTED`. On anything but `COMPLETED`,
`imageBase64` is null and `error` is filled in:

| Code                  | Meaning                                                     |
| --------------------- | ----------------------------------------------------------- |
| `INVALID_REQUEST`     | The message did not parse (missing `title`, bad enum, ...).  |
| `SOURCE_IMAGE_FAILED` | Avatar or cover unusable, and `RENDER_STRICT_IMAGES` is on.  |
| `RENDER_FAILED`       | Unexpected failure while drawing. Logged with a stack trace. |
| `OVERLOADED`          | No render slot free. Retry; the HTTP path returns 503.       |
| `TIMEOUT`             | The caller stopped waiting (HTTP path only).                 |

`imageBase64` is raw base64 with no data URI prefix - the frontend builds
`data:{contentType};base64,{imageBase64}`.

## Share links

The cards print short links and encode those in the QR code:

| Kind    | On the card            | Redirects to                        |
| ------- | ---------------------- | ----------------------------------- |
| `SQUAD` | `/s/zb9l8qk`           | `/community/squads/zb9l8qk`         |
| `USER`  | `/u/v83bYqnxOH...`     | `/profile/v83bYqnxOH...`            |
| `EVENT` | `/e/h1cj5p33`          | `/community/events?event=h1cj5p33`  |

Same obfuscated token, so no new endpoint and no lookup: the short routes in
`playbook-web/src/app/app.routes.ts` are pure redirects, and `server.ts` answers
them with a 302 on the web. `ShareLinks` in playbook-be builds both forms -
notifications and the sitemap keep using the long ones.

**Scanning a card opens the app, not the browser**, on a phone with Playbook
installed: the links are Android App Links, verified against
`playbook-web/public/.well-known/assetlinks.json`, and `MobilePlatformService`
routes the incoming URL into the Angular router. A build installed from Play is
signed with a different key than a local one, so its fingerprint has to be in
that file too - see `public/.well-known/README.md`. Without a verified file the
link still works, it just opens in a browser.

## Backpressure

This is the part worth understanding before changing anything.

- A process runs `RENDER_WORKERS` threads and accepts at most
  `RENDER_WORKERS + RENDER_QUEUE_SIZE` jobs at a time. Pillow releases the GIL
  for the heavy operations, so threads (not processes) are enough.
- When every slot is taken, the bridge **pauses its Kafka partitions**. The
  backlog then sits in Kafka - durable, ordered, and visible as consumer lag -
  instead of growing in this process's memory.
- Offsets are committed only after the result has been delivered back, and
  never past a message that is still in flight. A worker that dies mid-card
  replays that request; the backend should treat `requestId` as idempotent.
- Scale out by running more worker processes in the same consumer group. Scale
  up by raising `RENDER_WORKERS` to roughly the box's core count.
- Stopping a worker with SIGTERM drains it: in-flight cards finish, get
  delivered and get committed, and the group rebalances immediately. A worker
  that is killed outright holds its partitions for `KAFKA_SESSION_TIMEOUT_MS`
  (15s) before another takes over, and requests on those partitions wait.

On the HTTP path the same pool applies: callers wait up to
`RENDER_ADMISSION_WAIT_SECONDS` for a slot, then get a `503` with
`Retry-After`, which is a better answer for a waiting user than an open request
that eventually times out.

## Size budget

Kafka's default message limit is 1 MiB and base64 inflates the image by a
third, so the encoder targets `RENDER_MAX_BYTES` (600 kB by default). It tries
the requested format first, then WEBP, then JPEG at falling quality, then
scales the image down - the first result that fits wins. `format: "AUTO"`
starts from `RENDER_DEFAULT_FORMAT` (PNG), which keeps text crisp and usually
fits.

If you raise `RENDER_MAX_BYTES`, also raise `message.max.bytes` on the topic,
`KAFKA_MAX_MESSAGE_BYTES` here, and `max.request.size` /
`fetch.max.bytes` on the backend.

## HTTP API

The same contract over HTTP, for design iteration, for load checks without a
broker, and as a fallback if the Kafka path is down.

| Method | Path                       | Purpose                                   |
| ------ | -------------------------- | ----------------------------------------- |
| POST   | `/share-cards/render`      | Render, reply with the `RenderResult` JSON |
| POST   | `/share-cards/preview`     | Render, reply with the image bytes         |
| GET    | `/share-cards/sample/{kind}` | Demo card, `?layout=STORY&theme=ocean`   |
| GET    | `/share-cards/pool`        | Worker pool saturation                     |

```bash
curl -s localhost/share-cards/sample/USER?layout=STORY --output card.png
```

## Configuration

| Variable                        | Default                 | Notes                                    |
| ------------------------------- | ----------------------- | ---------------------------------------- |
| `KAFKA_BROKERS`                 | `localhost:9092`        | Comma separated                          |
| `KAFKA_REQUEST_TOPIC`           | `image-render-requests` |                                          |
| `KAFKA_RESULT_TOPIC`            | `image-render-results`  |                                          |
| `KAFKA_GROUP_ID`                | `image-render-workers`  | Same group across worker replicas        |
| `KAFKA_AUTO_OFFSET_RESET`       | `latest`                | Old requests are stale, skip them        |
| `KAFKA_SECURITY_PROTOCOL`       | `PLAINTEXT`             | `SSL` for the mTLS Redpanda deployments  |
| `KAFKA_SSL_CA_LOCATION`         | unset                   | mTLS CA bundle                           |
| `KAFKA_SSL_CERTIFICATE_LOCATION`| unset                   | Client certificate                       |
| `KAFKA_SSL_KEY_LOCATION`        | unset                   | Client key                               |
| `RENDER_WORKERS`                | `4`                     | Threads that draw cards                  |
| `RENDER_QUEUE_SIZE`             | `32`                    | Accepted-but-not-started jobs            |
| `RENDER_TIMEOUT_SECONDS`        | `20`                    | HTTP wait before `TIMEOUT`               |
| `RENDER_ADMISSION_WAIT_SECONDS` | `5`                     | HTTP wait for a slot before `503`        |
| `RENDER_MAX_BYTES`              | `600000`                | Encoded image ceiling                    |
| `RENDER_DEFAULT_FORMAT`         | `png`                   | Used by `format: "AUTO"`                 |
| `RENDER_FONT_REGULAR`           | unset                   | Path to a `.ttf`                         |
| `RENDER_FONT_BOLD`              | unset                   | Path to a `.ttf`                         |
| `RENDER_BRAND_NAME`             | `Playbook`              | Printed top left                         |
| `RENDER_ALLOW_REMOTE_IMAGES`    | `false`                 | Enables `avatarUrl` / `coverUrl`         |
| `RENDER_REMOTE_IMAGE_HOSTS`     | `[]`                    | JSON list, e.g. `'["cdn.example.org"]'`  |
| `RENDER_STRICT_IMAGES`          | `false`                 | Fail instead of dropping unusable photos |
| `RENDER_DEFAULT_COVER_DIR`      | unset                   | Photographs to use instead of generated cover art |

## Fonts

Without configuration the renderer picks the best system font it can find
(Segoe UI on Windows, DejaVu on the slim Docker images). To ship the brand
face, drop the files into `image_processing_service/static/fonts/` with
`regular` and `bold` in the filename (`Inter-Regular.ttf`, `Inter-Bold.ttf`) -
they are picked up automatically, and they make the container's output match a
developer's machine. Text is drawn with plain glyphs only; emoji render as tofu
in most system fonts.

## How playbook-be is wired

Already implemented; this is the map.

| Piece | Class |
| --- | --- |
| REST entry point, `POST /v1/blyf/share-card` | `controller/ShareCardController` |
| Payload building from entities | `service/implementation/ShareCardServiceImpl` |
| Pending request correlation | `service/ShareCardRegistry` |
| Kafka in/out | `kafka/producer/ShareCardProducer`, `kafka/consumer/ShareCardConsumer` |
| Wire DTOs | `model/dto/ShareCard*Dto` |

The frontend posts `{ kind, id, layout }` and nothing else: every string drawn
on the card is read from the database by `ShareCardServiceImpl`, so no caller
can order a Playbook branded image with text of their choosing. Private squads
and members-only events are checked against the caller's membership first.

Backend knobs (`blyf.playbook-be.share-card`): `timeout-seconds` (20),
`max-pending` (200, after which callers get 503) and `zone`
(`Asia/Kuala_Lumpur`, used to convert event times out of UTC before sending -
the renderer draws them exactly as given).

Two traps, both hit while wiring this up.

**The controller is async.** It returns a `CompletableFuture` so a servlet
thread is not parked for the second or two the render takes. That means the
container dispatches the request a *second* time to write the response, and
`AuthTokenFilter` is a `OncePerRequestFilter`, which by design does not re-run
on an ASYNC dispatch - so the security context is empty and the request 401s
*after* the card was already drawn. `WebSecurityConfig` therefore permits the
ASYNC dispatch, exactly as it already did for ERROR. Keep
`share-card.timeout-seconds` under 30s too, or Tomcat's async timeout fires
first (`spring.mvc.async.request-timeout` raises it).

**`shareCardResults` is the backend's second Spring Cloud Function bean**,
alongside `chatMessages`. Auto-detection only works when
there is exactly one candidate - with two, Spring Cloud Function binds neither
and both consumers go quiet with nothing but a startup warning. Every function
has to be listed:

```yaml
spring:
  cloud:
    function:
      definition: chatMessages;shareCardResults
```

Add to that list whenever a new `Consumer`/`Function` bean is introduced.

The bindings, next to the existing `chatMessages` ones in `application-*.yml`:

```yaml
spring:
  cloud:
    stream:
      bindings:
        shareCardRequests-out-0:
          destination: image-render-requests
          content-type: application/json
          producer:
            partition-key-expression: payload.requestId
        shareCardResults-in-0:
          destination: image-render-results
          content-type: application/json
          # No group on purpose. Every instance has to see every card, because
          # only the one holding the caller's HTTP request can answer it, and an
          # anonymous binding also starts at the latest offset so a restart never
          # replays yesterday's images.
```

At more than a couple of backend instances, broadcasting every card to every
instance gets expensive. Two ways out: give each instance its own reply topic
and set `replyTopic` per request, or keep one consumer group, park the result
in Redis under `requestId` and let the frontend poll
`GET /share-cards/{requestId}`.

## How playbook-web is wired

The existing share sheet (`components/shared/share-sheet`) now opens on a
**Link / Image card** switch. Link keeps everything it had - send to a friend,
copy, WhatsApp, Telegram, X, Facebook. Image renders the card, with a Post
(4:5) or Story (9:16) toggle, a preview, and Share / Download / Copy.

- `services/share/share.service.ts` holds the card state, calls
  `ApiService.renderShareCard`, caches the last six renders per target and
  layout, and hands the image to the OS.
- Sharing uses `navigator.share({ files })` on the web and Capacitor
  `Filesystem.writeFile` + `Share.share({ files })` on Android, so the card
  lands in Instagram or WhatsApp as an image rather than a link. Desktop
  browsers without file sharing fall back to a download.
- Posts have no card design, so the tab only appears for profiles, squads and
  events.
- 503 shows "lots of cards are being made right now", 504 shows a retry: the
  saturation path is visible to the user rather than a spinner that never ends.

## Running it locally

There is one broker for the whole project: the Redpanda in playbook-be's local
stack. This service does not run its own.

```bash
# 1. Infrastructure, if it is not already up (postgres, minio, redpanda)
docker compose -f ../playbook-be/src/main/resources/docker-compose.yml up -d

# 2. Topics, once per machine
docker exec playbook-redpanda rpk topic create image-render-requests -p 3 -r 1
docker exec playbook-redpanda rpk topic create image-render-results -p 3 -r 1
docker exec playbook-redpanda rpk topic alter-config image-render-results --set retention.ms=900000

# 3. Python environment, once per checkout. `make install` does this with uv;
#    without uv (Windows, say) it is plain venv + pip:
py -3.12 -m venv .venv          # python3 -m venv .venv on mac/linux
.venv\Scripts\activate          # source .venv/bin/activate on mac/linux
pip install -e .                # this is what puts the command below on PATH
cp .env.example .env            # local settings

# 4. The worker. No flags: .env points it at localhost:9092 and allows the
#    MinIO host so avatars load.
python main.py
```

`main.py` runs the worker straight from the checkout and needs no install; give
it arguments and it becomes the CLI (`python main.py sample-card --kind EVENT`).

The equivalents, once `pip install -e .` has run:

```bash
image_processing_service render-worker                     # console script
.venv\Scripts\image_processing_service.exe render-worker   # without activating
python -m image_processing_service.worker                  # module form
```

Then run playbook-be and playbook-web as usual and the Share sheet's image tab
works. Ctrl-C drains the worker cleanly.

Without a broker at all:

```bash
# Draw one card to a file
image_processing_service sample-card --kind EVENT --layout STORY --out card.png

# Or the HTTP twin, for poking at it in a browser
uvicorn image_processing_service.www:app --reload
```

To run the worker in Docker instead, `docker compose up -d render-worker`. It
joins playbook-local's network and uses the broker's **internal** listener,
`redpanda:29092`.

That detail is not optional. Redpanda advertises `localhost:9092` to external
clients, so a container that bootstraps via `host.docker.internal:9092`
connects once, is told the broker lives at `localhost:9092`, and then talks to
itself:

```
Connect to ipv4#127.0.0.1:9092 failed: Connection refused
```

Host processes use `localhost:9092`, containers use `redpanda:29092`. Same
broker, two listeners.
