import webview

html = """
<html>
<head><title>WebView Test</title></head>
<body style="font-family: Arial; padding: 30px;">
    <h2>PyWebView Test</h2>
    <button onclick="document.getElementById('result').innerText='Button Working!'">
        Click Me
    </button>
    <p id="result">Waiting...</p>
</body>
</html>
"""

window = webview.create_window(
    "WebView Diagnostic",
    html=html,
    width=500,
    height=400
)

webview.start(debug=True)
