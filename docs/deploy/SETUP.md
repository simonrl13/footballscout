# M7 deploy: account setup (owner)

Done by the owner, in this order. **Secrets never go into a chat, an issue, a commit or a GitHub secret**: passwords
and keys are typed only into the Neon console, your local `.env`, or Cloud Shell (into GCP Secret Manager).
GitHub Actions authenticates with short-lived OIDC tokens (Workload Identity Federation), so no key is stored in GitHub.

What Claude needs back, all **non-secret identifiers**: the Neon region, the GCP project ID, project number and
region, and the Workload Identity provider's resource name (step B7). Claude stores them as GitHub repository
*variables* (not secrets) and writes the deploy workflow.

Regions (decided 2026-10-14): GCP **`europe-west1`** (Belgium) with Neon **AWS Europe Central 1 (Frankfurt)**: the audience is mostly European, and the data stays in the EU.

## A. Neon (Postgres for the demo data, ~50 MB of the 0.5–1 GB free storage)
1. Sign up at neon.com; create a project `scout-demo`, Postgres 16, region **AWS Europe Central 1 (Frankfurt)**.
2. Open the SQL Editor on database `neondb` and run [neon_roles.sql](neon_roles.sql) after replacing its three
   password placeholders with passwords you generate locally. Then run [neon_verify.sql](neon_verify.sql) and check
   its output against the expected end state at its top.
3. From the Neon dashboard ("Connect"), build the three connection strings yourself, one per role, each ending in
   `?sslmode=require`. Keep them out of chat.
4. Add **only the loader's** string to your local `.env` as `NEON_LOADER_URL=...`, then run
   `uv run python -m scout.check_env` (it must print `.env: OK`).
5. Load the demo data (the file comes from `uv run --env-file .env python -m scout.demo_data export`, or from the
   GitHub release):
   `uv run --env-file .env python -m scout.demo_data import --url-env NEON_LOADER_URL`
   It prints the row counts (2,649 players, 37,375 passages). Reader and tracer strings go to GCP in step B5.
6. Run [neon_after_import.sql](neon_after_import.sql) (trace tables: no reader access, tracer only what the API
   writes), then [neon_verify.sql](neon_verify.sql) again. Repeat both after any re-import. Expected: **16 rows**:
   - the 13 from before the import (attributes, database, schema, the reader's default privilege, and
     `neondb_owner` as `admin` only on each role);
   - `scout_reader`: SELECT on **8 tables**, `demo_players, text_documents, text_extractions, text_mentions,
     text_passages, text_signals, wiki_snapshot_revisions, wikidata_players` (four of them hold data; the import's
     schema scripts create the other four empty), and nothing on `agent_*`;
   - `scout_tracer`: INSERT on `agent_calls, agent_violations`; SELECT on `agent_calls`.

## B. Google Cloud (Cloud Run for the API; Secret Manager for keys)
1. Create a project (note its **project ID** and **project number**) and link a billing account.
2. Billing → Budgets & alerts: a budget of **$1** with email alerts (50%, 90%, 100%).
3. Open Cloud Shell and set your values (not secrets):
   ```sh
   PROJECT_ID=your-project-id
   REGION=europe-west1
   PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
   gcloud config set project $PROJECT_ID
   gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com \
     iamcredentials.googleapis.com sts.googleapis.com
   gcloud artifacts repositories create scout --repository-format=docker --location=$REGION
   ```
4. Service accounts: one the API runs as, one GitHub deploys with.
   ```sh
   RUNTIME=scout-runtime@$PROJECT_ID.iam.gserviceaccount.com
   DEPLOYER=scout-deployer@$PROJECT_ID.iam.gserviceaccount.com
   gcloud iam service-accounts create scout-runtime --display-name="Scout API runtime"
   gcloud iam service-accounts create scout-deployer --display-name="Scout GitHub deployer"
   gcloud projects add-iam-policy-binding $PROJECT_ID --member=serviceAccount:$DEPLOYER --role=roles/run.admin
   gcloud artifacts repositories add-iam-policy-binding scout --location=$REGION \
     --member=serviceAccount:$DEPLOYER --role=roles/artifactregistry.writer
   gcloud iam service-accounts add-iam-policy-binding $RUNTIME \
     --member=serviceAccount:$DEPLOYER --role=roles/iam.serviceAccountUser
   ```
5. Secrets: you type each value at a hidden prompt (`read -rs`); nothing is echoed or saved in shell history.
   ```sh
   for s in anthropic-api-key reader-database-url tracer-database-url; do
     gcloud secrets create $s --replication-policy=automatic
     echo "value for $s:"; read -rs V; printf %s "$V" | gcloud secrets versions add $s --data-file=-; unset V
   done
   gcloud secrets create rate-limit-pepper --replication-policy=automatic
   python3 -c "import secrets; print(secrets.token_urlsafe(32), end='')" | gcloud secrets versions add rate-limit-pepper --data-file=-
   for s in anthropic-api-key reader-database-url tracer-database-url rate-limit-pepper; do
     gcloud secrets add-iam-policy-binding $s --member=serviceAccount:$RUNTIME --role=roles/secretmanager.secretAccessor
   done
   ```
   `anthropic-api-key`: a key from the dedicated "scout" workspace. `reader-database-url` / `tracer-database-url`:
   the Neon strings for `scout_reader` / `scout_tracer` from step A3.
6. Workload Identity Federation for GitHub Actions, limited to this repository's `main` branch:
   ```sh
   gcloud iam workload-identity-pools create github --location=global --display-name="GitHub Actions"
   gcloud iam workload-identity-pools providers create-oidc footballscout --location=global \
     --workload-identity-pool=github --issuer-uri="https://token.actions.githubusercontent.com" \
     --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
     --attribute-condition="assertion.repository=='simonrl13/footballscout' && assertion.ref=='refs/heads/main'"
   gcloud iam service-accounts add-iam-policy-binding $DEPLOYER --role=roles/iam.workloadIdentityUser \
     --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/simonrl13/footballscout"
   ```
7. Print the identifiers Claude needs (none of them is a secret):
   ```sh
   echo $PROJECT_ID $PROJECT_NUMBER $REGION
   gcloud iam workload-identity-pools providers describe footballscout --location=global \
     --workload-identity-pool=github --format='value(name)'
   ```

## C. Anthropic Console
1. Set the "scout" workspace's monthly spend limit to **$10**. The API's own cap is $0.50 a day (in code).

## D. Then Claude (no further accounts)
1. **Owner, once:** run [neon_rate_limits.sql](neon_rate_limits.sql) in the Neon SQL Editor (the per-IP request log;
   no passwords), then [neon_verify.sql](neon_verify.sql): **17 rows** (step A6's 16 plus `scout_tracer` DELETE on
   `agent_requests`; the tracer's INSERT and SELECT rows also list `agent_requests`; the reader's rows don't change).
   A later re-import creates the same table from `db/agent.sql`, so after one the expected count stays 17.
2. Claude: repository variables (`gh variable set`: `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_WIF_PROVIDER`,
   `AGENT_MODEL`, `AGENT_EFFORT`; none secret) and the deploy workflow
   ([.github/workflows/deploy.yml](../../.github/workflows/deploy.yml)): on every merge to `main` that touches the
   app, build the image, push it to Artifact Registry and deploy the `scout` service with `PUBLIC_DEMO=true` and the
   four secrets from Secret Manager; then a health check that needs the database.
3. Claude: the first deploy, a smoke test against the public URL (health, tools, one `/ask`, a 429 with a spoofed
   `X-Forwarded-For`), then a stop for the owner's review before the link is shared or added to the README.
