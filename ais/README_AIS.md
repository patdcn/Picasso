# AIS Vessel Tracker — infrastructure (ZIP 1)

Separate Dokploy Compose project. A picasso portal redeploy never touches
the database or interrupts the collector.

## Components

| Service | Rol |
|---|---|
| `ais-db` | TimescaleDB (pg17), volume `ais_pgdata`, alleen intern netwerk |
| `ais-collector` | Daemon: aisstream websocket → downsample 30 min → `positions` + `latest` |
| `ais-backup` | Nightly `pg_dump -Fc` om 03:00 UTC → `/data/backups` op `picasso_data` (14 d rotatie) |

Schema: `fleet` (keyed op IMO), `positions` (hypertable, index op mmsi+ts,
dedupe-index op mmsi+ts+source), `latest` (1 rij per vessel), `positions_hourly`
(continuous aggregate). Geen retention op raw data — data is heilig.

## Deploy (eenmalig)

1. **Dokploy → nieuw project → Compose**, zelfde GitHub repo, branch `main`,
   compose path `ais/docker-compose.yml`, autodeploy aan.
2. **Environment** in Dokploy voor dit project:
   - `POSTGRES_PASSWORD` = sterk wachtwoord (genereer, bewaar in je vault)
   - `AISSTREAM_KEY` = jouw aisstream.io API key
3. Deploy. Bij eerste start (leeg volume) draait `init/01_schema.sql`
   automatisch. Check `ais-db` logs op `create_hypertable` zonder errors.
4. **Seed** — Dokploy terminal op `ais-collector`:
   ```
   python seed/seed_fleet.py
   ```
   Verwacht: `seeded 58 rows -> fleet now holds 58 vessels (57 active)`.
   Idempotent; herdraaien is veilig. (Jana 201 staat inactief, geen MMSI.)
5. Collector logs tonen daarna:
   `subscribed: chunk 1/2 (50 MMSIs)` en na max. 5 min `rotated to chunk 2/2`.
   `stored <naam> ...` regels verschijnen zodra vessels binnen terrestrial
   AIS-bereik rapporteren. Elke 15 min een `stats:` regel.

## Controle-queries (Dokploy terminal op ais-db)

```
psql -U ais -d ais -c "SELECT count(*) FROM positions;"
psql -U ais -d ais -c "SELECT ship_name, ts, lat, lon, nav_status FROM latest ORDER BY ts DESC LIMIT 20;"
psql -U ais -d ais -c "SELECT f.name, count(*) FROM positions p JOIN fleet f ON f.mmsi=p.mmsi GROUP BY 1 ORDER BY 2 DESC LIMIT 10;"
```

## Portal-koppeling (ZIP 2, later)

Picasso-project krijgt env var:
```
AIS_DSN=postgresql://ais:<POSTGRES_PASSWORD>@ais-db:5432/ais
```
en `psycopg2-binary` in requirements. Beide projecten zitten op
`dokploy-network`, dus hostname `ais-db` resolvet direct.

## Ontwerpkeuzes / limieten

- **aisstream cap: 50 MMSIs per subscription.** Collector roteert chunks van
  ≤50 elke 5 min (swap-and-replace op dezelfde socket). Met 30-min sampling
  kost dat geen datapunten; schaalt tot ~300 vessels voor het knelt.
- **Terrestrial only**: vessels > ~40–70 NM uit de kust zijn onzichtbaar voor
  aisstream. Satelliet-vulling (Datalastic e.d.) komt later als tweede
  `source`; het dedupe-index vangt overlap af.
- **Downsample**: punt opslaan bij ≥30 min sinds vorige, of nav_status-wissel
  (breekt altijd door). Speed gate 50 kn verwerpt AIS-teleports; die bereiken
  ook `latest` niet.
- **`latest`** wordt per vessel max. 1×/min geüpsert — kaart leest nooit de
  hypertable voor "nu".
- Alle knoppen zijn env vars op `ais-collector` (SAMPLE_SECONDS, ROTATE_SECONDS,
  SPEED_GATE_KN, ...) — wijzigen = alleen service herstarten.

## Tweede bron: SeaVantage (satelliet, 15-min poll)

Service `ais-sv-poller` polt elke 15 min `/ship/snapshot` voor de hele vloot
(shipIds eenmalig geresolved via `/ship/search`, gecachet in `sv_ship`).
Data landt in dezelfde tabellen met `source='seavantage'`:
- `positions`: dedupe-index absorbeert ongewijzigde herhalingen
- `latest`: alleen bijgewerkt als de fix NIEUWER is dan wat er staat
  (stale satelliet overschrijft nooit verse terrestrial)
- `voyage`: gedeelde change-detection met de aisstream-collector

Setup:
1. Migratie `init/03_seavantage.sql` handmatig toepassen op de draaiende DB.
2. Dokploy env (ais-db project): `SV_USER`, `SV_PASSWORD`
   (Basic Auth per SVMP-docs; optioneel `SV_BASE_URL` als de base afwijkt
   van https://api.seavantage.com).
3. Eerst verifiëren: Dokploy terminal op `ais-sv-poller`:
   `python sv_probe.py 9698783` — toont status + response van search en
   snapshot. Kloppen paden/parameternamen niet met de Postman-docs, dan zijn
   ze via env vars te overriden (SV_SEARCH_PATH, SV_SEARCH_PARAM,
   SV_SNAPSHOT_PATH, SV_SNAPSHOT_PARAM) zonder codewijziging.
4. Bij 401 in de probe: check credentials, of stuur de Authorization-sectie
   uit de Postman-docs door (mogelijk API-key header i.p.v. Basic Auth).

## Backup & restore

Nightly dump landt als `/data/backups/ais_YYYYMMDD.dump` op de bestaande
`picasso_data` volume — je huidige off-VPS sync neemt hem dus mee. Restore:
```
pg_restore -h ais-db -U ais -d ais --clean --if-exists ais_YYYYMMDD.dump
```
Doe na de eerste week één proef-restore naar een scratch-db; een dump die je
nooit getest hebt is geen backup.
