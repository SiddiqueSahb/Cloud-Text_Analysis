import boto3
import re
import statistics
import json

s3 = boto3.client("s3")

STOP_WORDS = [
    "i", "me", "my", "myself", "we", "our", "ours", "ourselves",
    "you", "your", "yours", "yourself", "yourselves",
    "he", "him", "his", "himself", "she", "her", "hers", "herself",
    "it", "its", "itself", "they", "them", "their", "theirs",
    "themselves", "what", "which", "who", "whom", "this", "that",
    "these", "those", "am", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "having", "do", "does", "did",
    "doing", "a", "an", "the", "and", "but", "if", "or", "because",
    "as", "until", "while", "of", "at", "by", "for", "with", "about",
    "against", "between", "into", "through", "during", "before",
    "after", "above", "below", "to", "from", "up", "down", "in",
    "out", "on", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all",
    "any", "both", "each", "few", "more", "most", "other", "some",
    "such", "no", "nor", "not", "only", "own", "same", "so", "than",
    "too", "very", "s", "t", "can", "will", "just", "don", "should",
    "now"
]


def word_frequency(text, top_n=20):
    word_count = {}
    clean_text = re.sub(r"[^a-z0-9'\s]", " ", text.lower())
    words = clean_text.split()
    for word in words:
        if word and word not in STOP_WORDS:
            word_count[word] = word_count.get(word, 0) + 1
    return sorted(word_count.items(), key=lambda x: x[1], reverse=True)[:top_n]


def sent_start_words(text, top_n=10):
    start_word_ct = {}
    sentences = re.split(r"[.!?]\s+", text)
    for sent in sentences:
        cl_sentence = re.sub(r"[^a-z0-9\s]", "", sent.lower()).strip()
        if not cl_sentence:
            continue
        words = cl_sentence.split()
        first = words[0]
        if first not in STOP_WORDS:
            start_word_ct[first] = start_word_ct.get(first, 0) + 1
    return sorted(start_word_ct.items(), key=lambda x: x[1], reverse=True)[:top_n]


def sentence_length_distribution(text):
    sentences = re.split(r"[.!?]\s+", text)
    lengths = []
    for s in sentences:
        cl = re.sub(r"[^a-z0-9\s]", "", s.lower()).strip()
        if cl:
            lengths.append(len(cl.split()))

    if not lengths:
        return {"mean": 0, "median": 0, "stdev": 0}

    return {
        "mean": round(statistics.mean(lengths), 2),
        "median": statistics.median(lengths),
        "stdev": round(statistics.stdev(lengths), 2) if len(lengths) > 1 else 0
    }


def lambda_handler(event, context):
    """
    API Gateway proxy request expected:
    {
      "body": "{\"input_bucket\":\"...\",\"input_key\":\"...\",\"analyses\":[\"word_freq\",\"sent_start\"]}"
    }
    """
    try:
        # Support API Gateway proxy and direct invoke
        if "body" in event:
            body = json.loads(event["body"] or "{}")
        else:
            body = event

        input_bucket = body["input_bucket"]
        input_key = body["input_key"]

        # -------- NEW: analyses selection (default = all) --------
        allowed = {"word_freq", "sent_start", "sent_len"}
        analyses = body.get("analyses")

        if not analyses:
            analyses = ["word_freq", "sent_start", "sent_len"]

        analyses = [a for a in analyses if a in allowed]

        if not analyses:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "No valid analyses selected."}),
            }

        # Read text from S3
        obj = s3.get_object(Bucket=input_bucket, Key=input_key)
        text = obj["Body"].read().decode("utf-8")

        # Run only selected analyses
        result = {"analyses_ran": analyses}

        if "word_freq" in analyses:
            result["top_20_words"] = word_frequency(text)

        if "sent_start" in analyses:
            result["top_sentence_start_words"] = sent_start_words(text)

        if "sent_len" in analyses:
            result["sentence_length_stats"] = sentence_length_distribution(text)

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(result),
        }

    except Exception as e:
        print(f"Error in Lambda: {e}")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)}),
        }
