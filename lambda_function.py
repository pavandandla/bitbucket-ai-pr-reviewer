import json
import os
import logging
from bitbucket_client import BitbucketClient
from openai_client import OpenAIClient

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    """
    Main AWS Lambda handler for Bitbucket PR code reviews.
    
    Args:
        event (dict): AWS Lambda event object containing Bitbucket webhook payload
        context (object): AWS Lambda context object
        
    Returns:
        dict: Response object with status code and message
    """
    try:
        logger.info("Received event: %s", json.dumps(event))
        
        # Parse event body if it's a string
        if isinstance(event.get('body'), str):
            payload = json.loads(event['body'])
        else:
            payload = event.get('body', {})
            
        # Validate that this is a pull request event
        if not is_pull_request_event(payload):
            return format_response(400, {"message": "Not a valid pull request event"})
        
        # Extract PR information
        pr_info = extract_pr_info(payload)
        logger.info("Processing PR: %s", pr_info)
        
        # Initialize API clients
        bitbucket = BitbucketClient(
            username=os.environ.get('BITBUCKET_USERNAME'),
            app_password=os.environ.get('BITBUCKET_APP_PASSWORD')
        )
        openai = OpenAIClient(
            api_key=os.environ.get('OPENAI_API_KEY'),
            #model=os.environ.get('OPENAI_MODEL', 'gpt-4-1106-preview')
        )
        
        # Get PR diff
        logger.info(f"Fetching diff for PR #{pr_info['id']} in {pr_info['repo_workspace']}/{pr_info['repo_slug']}")
        diff_content = bitbucket.get_pr_diff(
            workspace=pr_info['repo_workspace'],
            repo_slug=pr_info['repo_slug'],
            pr_id=pr_info['id']
        )
        
        # Generate review using OpenAI
        logger.info("Generating review with OpenAI")
        review_comments = openai.generate_review(diff_content, pr_info)
        logger.info(f"Generated {len(review_comments)} review comments")
        
        # Post comments to Bitbucket PR
        logger.info("Posting review comments to Bitbucket")
        bitbucket.post_pr_comments(
            workspace=pr_info['repo_workspace'],
            repo_slug=pr_info['repo_slug'],
            pr_id=pr_info['id'],
            comments=review_comments
        )
        
        return format_response(200, {
            "message": "Code review completed successfully",
            "pr_id": pr_info['id'],
            "comments_added": len(review_comments)
        })
        
    except Exception as e:
        logger.error("Error processing PR review: %s", str(e), exc_info=True)
        return format_response(500, {
            "message": "Error processing code review",
            "error": str(e)
        })

def is_pull_request_event(payload):
    """
    Check if the webhook event is for a pull request.
    
    Args:
        payload (dict): Webhook payload
        
    Returns:
        bool: True if it's a pull request event
    """
    # Validate that we received a proper PR event payload
    # Bitbucket's webhook payload structure for PRs
    return (payload and 
            payload.get('pullrequest') and 
            payload.get('repository') and
            payload.get('action') in ['created', 'updated'])

def extract_pr_info(payload):
    """
    Extract relevant pull request information from webhook payload.
    
    Args:
        payload (dict): Webhook payload
        
    Returns:
        dict: Pull request information
    """
    pr = payload['pullrequest']
    repo = pr['destination']['repository']
    
    return {
        'id': pr['id'],
        'title': pr['title'],
        'description': pr.get('description', ''),
        'author': pr['author']['display_name'],
        'repo_name': repo['name'],
        'repo_slug': repo['full_name'].split('/')[-1],
        'repo_workspace': repo.get('workspace', {}).get('slug') or os.environ.get('BITBUCKET_WORKSPACE'),
        'source_branch': pr['source']['branch']['name'],
        'destination_branch': pr['destination']['branch']['name'],
        'diff_url': pr['links']['diff']['href']
    }

def format_response(status_code, body):
    """
    Format Lambda response.
    
    Args:
        status_code (int): HTTP status code
        body (dict): Response body
        
    Returns:
        dict: Formatted response
    """
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json'
        },
        'body': json.dumps(body)
    } 