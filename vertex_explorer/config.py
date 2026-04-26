PROJECT = "martin-test-datalab"
LOCATIONS = ["europe-west3", "europe-west4"]

UA_LOOKBACK_DAYS = 7
UA_PREFIXES = [
    "go-model-treebased-install-prediction",
    "tensorflow-install-prediction",
    "tensorflow-action-prediction",
    "tensorflow-audience-similarity",
    "tensorflow-win-price-prediction",
]

RUN_STATE_STYLE = {
    "PIPELINE_STATE_SUCCEEDED": "green",
    "PIPELINE_STATE_RUNNING": "cyan",
    "PIPELINE_STATE_FAILED": "red",
    "PIPELINE_STATE_CANCELLED": "yellow",
    "PIPELINE_STATE_CANCELLING": "yellow",
}
