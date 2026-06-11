# GCP Commands

**Build + Deploy + IAM:**

```
cd ~/Documents/Work/Devops/wiso-rag/wisorag-corrections
git checkout develop
git pull origin develop

gcloud builds submit \
    --tag us-central1-docker.pkg.dev/ragai-staging/wiso-ai/wiso-ai-api:latest \
    --project=ragai-staging . && \
gcloud run deploy wiso-ai-api \
    --image=us-central1-docker.pkg.dev/ragai-staging/wiso-ai/wiso-ai-api:latest \
    --region=us-central1 \
    --platform=managed \
    --no-allow-unauthenticated \
    --service-account=rag-api-sa@ragai-staging.iam.gserviceaccount.com \
    --set-secrets=ALLOYDB_PASSWORD=ALLOYDB_PRIMARY_PASSWORD:latest,GEMINI_API_KEY=GEMINI_API_KEY:latest \
    --set-env-vars=ALLOYDB_HOST=10.187.0.2,ALLOYDB_DATABASE=wiso_ai_db,ALLOYDB_USER=postgres,VERTEX_AI_PROJECT=ragai-staging,VERTEX_AI_LOCATION=us-central1,BIGQUERY_PROJECT=simula-ipd-produ,ENVIRONMENT=dev \
    --vpc-connector=wiso-ai-vpc-connector \
    --vpc-egress=all-traffic \
    --min-instances=1 \
    --max-instances=10 \
    --memory=2Gi \
    --cpu=2 \
    --timeout=60 \
    --concurrency=80 && \
gcloud run services add-iam-policy-binding wiso-ai-api \
    --region=us-central1 \
    --project=ragai-staging \
    --member="allUsers" \
    --role="roles/run.invoker"
```
