from flask import Flask, request, render_template
import boto3
import uuid
import json
import http.client
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

# -------------------------
# S3 CONFIG
# -------------------------
UPLOAD_BUCKET = "input-a2-bucket"
s3 = boto3.client("s3")

# -------------------------
# API GATEWAY CONFIG
# -------------------------
API_HOST = "z90kpv5bd9.execute-api.us-east-1.amazonaws.com"
API_STAGE = "default"
API_RESOURCE = "s3-trigger-lambda"   # POST /default/s3-trigger-lambda

MAX_WORKERS = 5

ALLOWED_ANALYSES = {"word_freq", "sent_start", "sent_len"}
DEFAULT_ANALYSES = ["word_freq", "sent_start", "sent_len"]


def call_lambda_via_api(input_bucket: str, input_key: str, analyses: list[str]) -> dict:
    """
    Call Lambda via API Gateway and return parsed JSON.
    """
    conn = http.client.HTTPSConnection(API_HOST)

    payload = json.dumps({
        "input_bucket": input_bucket,
        "input_key": input_key,
        "analyses": analyses
    })

    path = f"/{API_STAGE}/{API_RESOURCE}"
    headers = {"Content-Type": "application/json"}

    conn.request("POST", path, body=payload, headers=headers)
    response = conn.getresponse()
    raw_data = response.read().decode("utf-8")

    if response.status != 200:
        raise Exception(f"Lambda/API error {response.status}: {raw_data}")

    # API Gateway proxy usually returns {"statusCode":..., "body":"..."}
    try:
        outer = json.loads(raw_data)
    except json.JSONDecodeError as e:
        raise Exception(f"Invalid JSON from API Gateway: {e} | data={raw_data}")

    if isinstance(outer, dict) and "body" in outer:
        inner = outer["body"]
        if not inner:
            raise Exception("Lambda returned empty body")
        try:
            return json.loads(inner)
        except json.JSONDecodeError as e:
            raise Exception(f"Invalid JSON inside Lambda body: {e} | body={inner}")

    return outer


# -------------------------
# ROUTES
# -------------------------

@app.route("/", methods=["GET"])
def upload_page():
    return render_template("upload.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    files = request.files.getlist("files")

    if not files or files == [None]:
        return render_template("upload.html", error="No files uploaded.")

    # -------- NEW: read analyses selection (default = all) --------
    selected = request.form.getlist("analyses")
    selected = [a for a in selected if a in ALLOWED_ANALYSES]
    if not selected:
        selected = DEFAULT_ANALYSES

    uploaded = []

    # -------- 1) Upload files to S3 --------
    try:
        for f in files:
            if not f or f.filename.strip() == "":
                continue

            key = f"uploads/{uuid.uuid4()}_{f.filename}"

            s3.put_object(
                Bucket=UPLOAD_BUCKET,
                Key=key,
                Body=f.read()
            )

            uploaded.append({"filename": f.filename, "s3_key": key})

        if not uploaded:
            return render_template("upload.html", error="No valid files uploaded.")

    except Exception as e:
        return render_template("upload.html", error=f"Error uploading files: {str(e)}")

    # -------- 2) Call Lambda in parallel --------
    results = []

    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_map = {
                executor.submit(call_lambda_via_api, UPLOAD_BUCKET, item["s3_key"], selected): item
                for item in uploaded
            }

            for future in as_completed(future_map):
                item = future_map[future]
                try:
                    analysis = future.result()
                    results.append({"filename": item["filename"], "data": analysis, "error": None})
                except Exception as err:
                    results.append({"filename": item["filename"], "data": None, "error": str(err)})

    except Exception as e:
        return render_template("upload.html", error=f"Error analyzing files: {str(e)}")

    # -------- 3) Render results --------
    return render_template("data.html", results=results)


# -------------------------
# RUN ON EC2
# -------------------------
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8080)
