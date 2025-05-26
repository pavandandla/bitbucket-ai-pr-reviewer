from flask import Flask, request, jsonify
import logging
from lambda_function import lambda_handler

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

@app.route('/webhook', methods=['POST'])
def webhook():
    event = {'body': request.get_json()}
    response = lambda_handler(event, None)
    return (response['body'], response['statusCode'], response.get('headers', {}))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
