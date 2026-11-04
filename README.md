# Meesho: cloud vs on premises cost model (IT457, Group 3)

A web application that models a Meesho like workload (1 PB of images, 10 billion CDN requests a day,
3x sale day peaks) on **AWS**, **GCP**, a **hybrid** (cloud edge + self hosted cache/DB, as Meesho did) and
**on premises**, and finds the **break even month** where leaving the cloud becomes cheaper.

The workload is hypothetical and scaled from public figures. It is **not** Meesho's real bill.

**Stack:** Python + FastAPI backend, plain HTML + CSS + JavaScript front end (Chart.js for charts).

## Structure
```
|   README.md
|   requirements.txt
|   
+---backend
|   |   api.py
|   |   experiments.py
|   |   model.py
|   |   prices.json
|   |   
|   +---results
|   |       calculator_inputs.csv
|   |       fig1_monthly_cost.png
|   |       fig2_breakeven.png
|   |       fig3_sensitivity.png
|   |       fig4_scaling.png
|   |       fig5_heatmap.png
|   |       fig6_transit_parity.png
|   |       results.json
|   |       
|   +---tests
|           test_api.py
|           test_cloud_model.py
|           test_onprem_breakeven.py 
|           
\---frontend
    |   app.js
    |   index.html
    |   style.css
    |   theme.js
    |   
    \---vendor
            chart.umd.js
```

## Run locally
```bash
pip install -r requirements.txt
cd backend
pytest -q                        
uvicorn api:app --port 8000         #API docs: /docs
python experiments.py            # regenerate results/
python loadtest.py               # starts its own server; or: python loadtest.py https://your-url
```

## API
| Endpoint | Purpose |
|---|---|
| `GET /schema` | Input fields with label, range, unit, default (the front end builds its form from this) |
| `GET /prices` | Price table with status and source |
| `POST /evaluate` | Run the model. Body: any subset of the input fields plus `commit` (`3y`,`1y`,`on_demand`) and `onprem_case` (`low`,`base`,`high`). Out of range values return 422. |
| `GET /health` | Liveness check |
