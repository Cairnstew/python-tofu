import functions_framework


@functions_framework.http
def hello_http(request):
    """HTTP Cloud Run function entry point."""
    return "hello from python-tofu"
