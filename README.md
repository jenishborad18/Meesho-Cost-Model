# Meesho: cloud vs on premises cost model (IT457, Group 3)

A web application that models a Meesho like workload (1 PB of images, 10 billion CDN requests a day,
3x sale day peaks) on **AWS**, **GCP**, a **hybrid** (cloud edge + self hosted cache/DB, as Meesho did) and
**on premises**, and finds the **break even month** where leaving the cloud becomes cheaper.

The workload is hypothetical and scaled from public figures. It is **not** Meesho's real bill.

**Stack:** Python + FastAPI backend, plain HTML + CSS + JavaScript front end (Chart.js for charts).

## Structure
```
backend/

frontend/

requirements.txt 
```

## API
| Endpoint | Purpose |
|---|---|
| `GET /schema` | Input fields with label, range, unit, default (the front end builds its form from this) |
| `GET /prices` | Price table with status and source |
| `POST /evaluate` | Run the model. Body: any subset of the input fields plus `commit` (`3y`,`1y`,`on_demand`) and `onprem_case` (`low`,`base`,`high`). Out of range values return 422. |
| `GET /health` | Liveness check |
