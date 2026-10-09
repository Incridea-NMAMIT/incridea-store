# Incridea Store

Official black-and-white Android app catalog for https://apps.incridea.in. This repository is public; APK source repositories may remain private. The store is website-only by explicit exception to web/Android feature parity.

Publication fails closed if a target release contains unexpected assets or
ambiguous APK names, or if a candidate signing key differs from catalog history.
All matrix candidates receive these checks before any release is published;
asset policy is checked again immediately before each publication. Investigate
and repair conflicting drafts through an authorized manual review. The publisher
does not delete assets or migrate signing keys automatically. GitHub repository
writers can still modify releases outside this workflow; protect that authority.

## Local development and hosting

Node 24: `npm ci`, then `npm run dev` (localhost:3007). `npm run build` produces `dist`. `npm test` covers release publication and bootstrap integration contracts. No signing secrets or GitHub tokens belong in frontend environment variables.

VPS: build the Dockerfile, setting `PROD_ENV=VPS`. The container serves `/health/ready` with the `RELEASE_SHA` supplied by the deployment runner. Vercel: import this repo, select Vite, set `PROD_ENV=VERCEL`, and use the checked-in rewrites. Public catalog and release assets work identically on both hosts. No database, background worker, private download proxy, or local APK storage is required.

## First-time GitHub configuration

1. Create **public** `Incridea-NMAMIT/incridea-store`, push main. Store has its own reusable image-build workflow so initial image publication does not depend on Deploy being online. Keep source repositories private if desired. Enable Actions read/write workflow permissions for this store. Do not restrict `catalog` branch updates to human-only approvals; restrict its writers to automation/admins.
2. Create a GitHub App installed on store, Dashboard, Operations, and Deploy, with repository **Actions: read** and **Contents: read/write**. Set repository/organization variable `STORE_GITHUB_APP_ID` and secret `STORE_GITHUB_APP_PRIVATE_KEY`, limited to these four repositories. Each workflow requests short-lived tokens scoped to the source repositories with Actions read or the store alone with Contents write. The store's own `GITHUB_TOKEN` writes releases/catalog. PR jobs never receive publishing credentials.
3. Set store variable `STORE_SIGNING_FINGERPRINTS` to a JSON object containing all four production signing certificate SHA-256 fingerprints, keyed by `in.incridea.dashboard`, `in.incridea.operations`, `in.incridea.pronite`, and `in.incridea.deploy`. Obtain fingerprints from the production signing certificates, not arbitrary uploaded APKs. Colons and uppercase are accepted. Signing key changes deliberately fail publication until migration is reviewed.
4. In Dashboard, Operations, and Deploy, configure the existing `android-signing` environment and signing secrets, set `ANDROID_SIGNING_ENABLED=true`, and set `STORE_PUBLISH_ENABLED=true`. Set store variable `STORE_PUBLISH_SINCE` to the UTC timestamp when these versioned signed-build workflows were enabled (for example `2026-10-08T12:00:00Z`); scheduled recovery scans successful runs since that cutover. Existing environment protection still governs signing. Store publishing does **not** require `DEPLOY_PORTAL_ENABLED` or publication approval in the private portal.
5. The initialization workflow creates the `catalog` branch with an empty catalog. Every successful completed main push with signed Android jobs dispatches a store publication. The publisher checks GitHub's run/job/artifact evidence and the APK itself, and copies only the APK into public releases. AABs remain in source CI artifacts. All four apps keep their existing login and authorization.
6. For a verified existing build, run **Publish verified Android releases** manually with the source repository and run ID. Only builds using `1000 + run_number` / `1.0.0+ci.N` versions qualify. Older APKs with versionCode 1 need a new signed build. Public release tags contain the app slug, version code, and source SHA prefix; source commit IDs are public, but private source files and CI logs are not copied.

Actions concurrency serializes writers. GitHub can replace pending runs in a concurrency group: the scheduled reconciliation workflow scans completed signed runs to recover notifications lost to concurrency, failed dispatches, or transient publication errors. Manual replay is also safe. Existing releases remain downloadable indefinitely; retrying a run verifies matching bytes and leaves the catalog unchanged. Older runs append history without replacing the greatest versionCode. A failed upload leaves a draft release; the catalog changes only after all releases are complete. GitHub's Contents API rejects conflicting catalog writes.

## VPS first run

The first-run script lives in `incridea-deploy/scripts/bootstrap-vps.sh`. Before running it:

- Point `deploy.incridea.in` and `apps.incridea.in` A/AAAA records to this VPS (remove stale AAAA records).
- Publish attested container images for Deploy and Store. Supply their immutable `ghcr.io/incridea-nmamit/...@sha256:...` image references and exact 40-character commit SHAs when prompted. The read-only bootstrap registry token must read both repositories/packages.
- Configure common auth for the deployment portal as before.

Bootstrap validates both DNS names, provisions certificates, seeds Store as a frontend application and production environment, runs the Store image on localhost:3007 (container port 8080), and adds the route through the existing runner. Re-running preserves active deployments, handles a missing Store, and checks public HTTPS before marking setup complete. Store bootstrap progress is separate from the portal marker. Future site-code updates use the portal's existing preview/confirmation deployment controls; catalog updates need no site deployment. Configure Store staging in the portal before enabling `DEPLOY_PORTAL_ENABLED=true` on Store.

Recovery: inspect `sudo docker logs incridea-incridea-store-production-blue`, `sudo nginx -t`, and `sudo journalctl -u incridea-runner`. Fix DNS/credentials and rerun bootstrap. If a normal portal release has replaced the initial Store container, bootstrap uses registered route/slot state instead of recreating the bootstrap image. Never delete release assets to fix catalog failures; replay the publisher instead.

## App content

Curated descriptions and categories live in `src/apps.json`. Add real Android screenshots under `public/screenshots/`, then set `screenshots` to `{ "src": "/screenshots/operations-home.png", "alt": "Operations home screen" }` objects. Images render in grayscale. Do not use web screenshots or invented screens as Android screenshots. Until genuine screenshots are supplied, app pages say they are not yet available. Catalog metadata is validated before rendering, and downloads are restricted to this repository's GitHub Release APK URLs.

Android version codes derive from the existing `.github/workflows/deploy-ci.yml` run sequence. Keep that workflow's identity and counter; replacing it/resetting the run sequence requires a reviewed version-code offset change. GitHub Apps, signing configuration, live APK verification, DNS/TLS, and device upgrades must be validated in the real environment before calling deployment complete.
