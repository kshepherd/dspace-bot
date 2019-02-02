import os
import time
import re
import sys
import json
import logging
import traceback
from slackclient import SlackClient
from github import Github
import github
from jira import JIRA

logging.basicConfig()
log = logging.getLogger()

# instantiate Github client
# replace this with your token or set your own env variable GITHUB_API_TOKEN
github_client = Github(os.environ.get("GITHUB_API_TOKEN"))

# instantiate Slack client
# replace this with your token or set your own env variable SLACK_BOT_TOKEN
slack_client = SlackClient(os.environ.get('SLACK_BOT_TOKEN'))

# instantiate jira client -- replace with your own JIRA instance base URL
jira = JIRA('https://jira.duraspace.org')

dspace_bot_id = None

# constants
RTM_READ_DELAY = 1 # 1 second delay between reading from RTM
EXAMPLE_COMMAND = "do"
MENTION_REGEX = "^<@(|[WU].+?)>(.*)"
MAGIC_WORDS_REGEX = "(PR|DSPR|DS)[ ]?[-#]?([0-9]+)"
GET_PR_REGEX = "(PR|DSPR)[ ]?[-#]?([0-9]+)(.*)"
GET_JIRA_ISSUE_REGEX = "(DS)[ ]?[-#]?([0-9]+)(.*)"
GET_COMMIT_REGEX = "(commit) ([abcdef0-9]{6,40})(.*)"
COMMIT_SHA_REGEX = "commit ([abcdef0-9]{6})"
SEARCH_REVIEWS_REGEX = "(quick win)[^0-9]*([0-9]\.[0-9])(.*)$"
SEARCH_SORT_REGEX = "by (date|updated|recent|created|interaction|id)"
DSPACE_DSPACE = 3743376 # internal ID of dspace/dspace repository

magic_words_cooldown = {}


def cooling_down(label):
    """
        Determine if a command is still in cooldown or if we can run it again safely
    :param label: the label/command eg 'DS-1234'
    :return: boolean representing "is in cooldown"
    """
    if (label) in magic_words_cooldown:
        elapsed = time.time() - magic_words_cooldown[label]
        print "Time elapsed since last time "+label+" was requested: "+str(elapsed)
        return True
    else:
        magic_words_cooldown[label] = time.time()
        print "Response for "+label+" logged at "+magic_words_cooldown[label].__str__()
        return False

    return False

def parse_slack_events(slack_events):
    """
        Parses a list of events coming from the Slack RTM API to find bot commands.
        If a bot command is found, this function returns a tuple of command and channel.
        If its not found, then this function returns None, None.
    """
    for event in slack_events:
        if event["type"] == "message" and not "subtype" in event:
            command_data = parse_magic_phrases(event["text"])
            if command_data is not None:
                command_data['channel'] = event['channel']
                return command_data
    return None

def parse_bot_commands(slack_events):
    """
        Parses a list of events coming from the Slack RTM API to find bot commands.
        If a bot command is found, this function returns a tuple of command and channel.
        If its not found, then this function returns None, None.
    """
    for event in slack_events:
        if event["type"] == "message" and not "subtype" in event:
            user_id, message = parse_direct_mention(event["text"])
            reference, number = parse_magic_words(event["text"])
            # Mentions a magic word without direct mention necessary
            if reference is not None and number is not None:
                return reference, number, event["channel"]
            # Direct message
            if user_id == dspace_bot_id:
                return message, user_id, event["channel"]
    return None, None, None

def parse_magic_phrases(message_text):
    quick_wins = re.search(SEARCH_REVIEWS_REGEX, message_text, re.IGNORECASE)
    #categories = {'quick_wins':SEARCH_REVIEWS_REGEX,'issues':MAGIC_WORDS_REGEX}
    command_data = {}

    categories = [
        {'name': 'quick_win',
         'regex': SEARCH_REVIEWS_REGEX,
         'groups': ['text', 'command', 'milestone', 'optional']
         },
        {'name': 'get_pr',
         'regex': GET_PR_REGEX,
         'groups': ['text', 'command', 'number', 'optional']
         },
        {'name': 'get_jira_issue',
         'regex': GET_JIRA_ISSUE_REGEX,
         'groups': ['text', 'command', 'number', 'optional']
         },
        {'name': 'get_commit',
         'regex': GET_COMMIT_REGEX,
         'groups': ['text', 'command', 'sha', 'optional']
         }
    ]

    for c in categories:
        matches = re.search(c['regex'], message_text, re.IGNORECASE)
        if matches: # and len(matches.groups()) == len(c['groups']):
            print "Found match for %s" % c['name']
            for index, group in enumerate(c['groups']):
                # i could enumerate actual matches groups instead... either way have to handle index mismatches
                # unless i make c[groups] a dict like {0:'text,1:'command', .... } ?
                try:
                    command_data[group] = matches.group(index)
                except IndexError:
                    print "Encountered an index error for %s, group: %s, index: %s" % (c['name'], group, index)
                    # TODO log.error()
                    return None

            command_data['name'] = c['name']
            for k, v in command_data.items():
                print "%s = %s" % (k, v)
            return command_data if command_data else None
    return None


def parse_magic_words(message_text):
    """
        Finds message text that matches some 'magic words' containing references
        to things like JIRA issues, Github PRs, commit hashes, code line numbers
        and general commands that don't need a direct mention
    """
    matches = re.search(MAGIC_WORDS_REGEX, message_text, re.IGNORECASE)
    commits = re.search(COMMIT_SHA_REGEX, message_text, re.IGNORECASE)
    quick_wins = re.search(SEARCH_REVIEWS_REGEX, message_text, re.IGNORECASE)

    if matches:
        print ("Found some magic words: reference = %s, number = %s" % (matches.group(1), matches.group(2)))
        # now, quickly iterate cooldown dict and wipe things that elapsed more than 60 seconds ago
        for k, v in magic_words_cooldown.items():
            # if more than 60 seconds have passed, wipe it
             if time.time() - v > 60:
                 del magic_words_cooldown[k]
        return (matches.group(1), matches.group(2).strip()) if matches else (None, None)
    elif commits:
        return "sha",commits.group(1).strip()
    elif quick_wins and False:
        print ("Found some quick wins: reference = %s, number = %s" % (quick_wins.group(1), quick_wins.group(2)))
        # now, quickly iterate cooldown dict and wipe things that elapsed more than 60 seconds ago
        for k, v in magic_words_cooldown.items():
            # if more than 60 seconds have passed, wipe it
            if time.time() - v > 60:
                del magic_words_cooldown[k]
        return (quick_wins.group(1), quick_wins.group(2).strip()) if quick_wins else (None, None)

    return (matches.group(1), matches.group(2).strip()) if matches else (None, None)


def parse_direct_mention(message_text):
    """
        Finds a direct mention (a mention that is at the beginning) in message text
        and returns the user ID which was mentioned. If there is no direct mention, returns None
    """
    matches = re.search(MENTION_REGEX, message_text)
    return (matches.group(1), matches.group(2).strip()) if matches else (None, None)


def send_response(message_text,channel):
    # Sends the response back to the channel
    slack_client.api_call(
        "chat.postMessage",
        channel=channel,
        text=message_text
    )


def handle_command(command, data, channel):
    """
        Executes bot command if the command is known
    """
    print "handle_command called with %s for %s" % (command, channel)
    # Default response is help text for the user
    #default_response = "Not sure what you mean. Try *{}*.".format(EXAMPLE_COMMAND)
    default_response = None

    # Finds and executes the given command, filling in response
    response = None

    # This is where you start to implement more commands!
    if command.startswith(EXAMPLE_COMMAND):
        response = "Sure...write some more code then I can do that!"

    # Github pull request info
    if (command == "PR" or command == "DSPR") and data is not None:
        response = fetch_pullrequest(data)

    if (command == "DS") and data is not None:
        response = fetch_jiraissue(data)

    if (command == "sha"):
        response = fetch_commit(data)

    if command == "get_jira_issue":
        response = fetch_jiraissue(data['number'])

    if command == "get_pr":
        # no optional handling, i don't think? could do verbosity though
        response = fetch_pullrequest(data['number'])

    if command == "get_commit":
        response = fetch_commit(data['sha'])

    if command == "quick_win":
        # test sorting since this is a search
        default_sort = "best match"
        sort_matches = re.search(SEARCH_SORT_REGEX, data['optional'], re.IGNORECASE)
        query = "repo:DSpace/DSpace is:open label:\"quick win\" milestone:"+data['milestone']
        if (sort_matches):
            query += " sort:"+sort_matches.group(2).strip()

        response = "*Top 5 quick wins for %s sorted by interaction* " \
                   "(say \"by created\" or \"by updated\" for recent PRs)\n\n" % data['milestone']
        response += search_pulls_simple(query)
    # Sends the response back to the channel
    #slack_client.api_call(
    #    "chat.postMessage",
    #    channel=channel,
    #    text=response or default_response
    #)
    send_response(response or default_response, channel)


def fetch_repos():
    """
        Fetch all Github repositories for a user
    """
    for repo in github_client.get_user().get_repos():
        print("%s %s %s" % (repo.url,repo.full_name,repo.id))


def fetch_jiraissue(data):
    """
        Fetch JIRA issues for a based on a numeric ID like 1234
        Since I'm always prepending DS- and using the Duraspace JIRA, in this case it's restricted
        to the DSpace project
    :param data: The issue ID without project code or prefix, eg 1234
    :return: a response string to be sent to the channel
    """
    label = "DS-%s" % data
    try:
        if cooling_down(label):
            return None
        else:
            issue = jira.issue(label)
            # Unfortunately remote links don't include Github PRs
            # but we can basically reproduce by searching Github
            """
            remote_links = jira.remote_links(label)
            #pprint(dir(issue.fields))
            for remote_link in remote_links:
                print remote_link.application.name
                print remote_link.relationship
                print remote_link.object.url
                print remote_link.object.title
                #print remote_link.object.summary
                print remote_link.object.status
            """
            # TODO: this should perhaps be a title search in regular search to avoid bad matches
            # -- it's a tradeoff as not all PRs are named nicely with DS-1234 keys
            pulls = search_pulls_for_issue("\""+label+"\"")

            #print issue.summary
            issue_type = issue.fields.issuetype or "Issue"
            versions = list(map(lambda x: x.name, issue.fields.versions))
            response = ("*ISSUE [DS-%s]*: %s\n%s reported by %s, created %s\nStatus: %s\tPriority: %s\tAffects: %s"
                "\n:clipboard: https://jira.duraspace.org/browse/%s" %
                (data,issue.fields.summary,issue_type,issue.fields.reporter,issue.fields.created,
                issue.fields.status,issue.fields.priority,(','.join(versions)),label))
            if len(pulls) > 0:
                response += "\n\n*Related pull requests* (by search for '%s'):\n" % label
                response += pulls

            return response

    except github.UnknownObjectException:
        return response


def fetch_pullrequest(data):
    """
    Fetch a single PR from Github for a particular repository and return a formatted response
    :param data: The PR ID without prefix, eg 1234
    :return: response string to be sent to the channel
    """
    label = "PR-%s" % data
    try:
        if cooling_down(label):
            return None
        else:
            number = int(data)
            repo = github_client.get_user().get_repo("DSpace").parent
            pull = repo.get_pull(number)
            milestone = getattr(pull.milestone,'title','none')
            jira_matches = re.search("DS-?([0-9]+)",pull.title)
            jira_link = (":clipboard: https://jira.duraspace.org/browse/DS-%s" % jira_matches.group(1)) if jira_matches else "No JIRA link?"

            response = ("*PULL #%s*: %s\nPR for *%s* by %s, created %s\nMilestone: %s\tState: %s\tReviews: %i\tMergeable: %s\n%s\n:github: %s" %
                (pull.number, pull.title, pull.base.ref, pull.user.name, pull.created_at, milestone, pull.state,
                pull.review_comments, pull.mergeable, jira_link, pull.html_url))

            return response
    except github.UnknownObjectException:
        response = ("Could not find a DSpace pull request with number %i." % number)
        return response
        """
    except Exception:
        print "Unexpected error:", sys.exc_info()[0]
        response = "Unexpected error:", sys.exc_info()[0]
        return response
        """


def fetch_commit(sha):
    """
    Fetch details about a single commit in Github, for a particular repo, based on partial or full SHA hash
    :param sha: partial or full SHA hash of the commit
    :return: response string to be sent to channel
    """
    repo = github_client.get_user().get_repo("DSpace").parent
    c = repo.get_commit(sha)
    if c and hasattr(c,'files'):
        files = list(map(lambda x: ("%s `+%i` `-%i` `(%i)`" % (x.filename,x.additions,x.deletions,x.changes)), c.files))
        response = ("Commit %s by %s on %s `+%i` `-%i` `(%i)`\n```%s```" % (sha[:6],c.commit.author.name,c.commit.author.date,
            c.stats.additions,c.stats.deletions,c.stats.total,c.commit.message))
        response += ("\n%s\n%i files changed" % (c.html_url,len(files)))
        if len(files) <=3 and len(files) > 0:
            response += "\n*Files*:\n%s" % '\n'.join(files)
        elif len(files) > 3:
            response += " (supressing details for >3 files, follow above link for more info)"
        return response

    return None

def search_pulls_simple(query):
    """
    Search a repo's PRs with the query supplied, base function so we can do these things:
    https://help.github.com/articles/searching-issues-and-pull-requests/
    :param query: a valid github search query
    :return: Formatted response to be sent to the channel
    """
    index = 0
    response = ""
    try:
        issues = github_client.search_issues(query)
        if issues:
            for issue in issues:
                index += 1
                if index > 5:
                    return response
                pr = issue.as_pull_request()
                reviews = pr.get_reviews()
                approvals = 0
                change_requests = 0
                total_comments = 0
                for review in reviews:
                    total_comments += 1
                    if review.state == "APPROVED":
                        approvals += 1
                    elif review.state == "CHANGES_REQUESTED":
                        change_requests += 1
                mergeable = ""
                if pr.mergeable_state == 'clean':
                    if approvals >= 2:
                        mergeable = "can be merged (+%s)" % approvals
                    elif approvals == 1:
                        mergeable = "needs another +1"
                    else:
                        mergeable = "needs >= 2 approvals"
                else:
                    if change_requests > 0:
                        mergeable = "blocked, changes requested"
                    else:
                        mergeable = "blocked (CI or merge conflict?)"

                review_state = ("%s review comments. %s approvals, %s changes requested. State: %s" % (total_comments, approvals, change_requests, mergeable))
                response += (":github: *#%s* %s\n%s\nhttps://github.com/DSpace/DSpace/pull/%s (Updated: %s)\n\n" % (issue.number, issue.title, review_state, issue.number, pr.updated_at))
        return response
    except github.UnknownObjectException:
        traceback.print_exc()
        response = ("Could not find a DSpace pull request with this search")
        return response


def search_pulls_for_issue(data):
    """
    Search a repo's PRs for references to a JIRA issue, to bring in related issues when displaying PR data
    :param data: the issue ID without project key or prefix, eg 1234
    :return: Formatted response to be sent to the channel
    """
    response = ""
    try:
        repo = github_client.get_user().get_repo("DSpace").parent
        # even though we hav eto specify, it looks like closed is searched too
        issues = repo.legacy_search_issues("open",data)
        if issues and len(issues) > 0:
            for issue in issues:
                # for some reason this triggers error.. maybe just for closed ones?
                #pull = issue.as_pull_request()
                #pr = getattr(open_pull,'pull_request',)
                #pprint(dir(issue))
                #pprint(open_pull.pull_request)
                response += (":github: *#%s* %s (%s)\nhttps://github.com/DSpace/DSpace/pull/%s\n" % (issue.number,issue.title,issue.state,issue.number))
        return response
    except github.UnknownObjectException:
        traceback.print_exc()
        response = ("Could not find a DSpace pull request with this search")
        return response


def fetch_pullrequests():
    """
    Fetch PRs for a user, with filters
    :return: nothing yet, just a test function...
    """
    try:
        for issue in github_client.get_user().get_issues(state='open', filter=filter):
            # Do something with this?
            send_response("DSPR # %s: %s",issue.number, issue.title)

        #log.debug("Found %d items" % len(items))
        #return items
    except Exception:
        log.error("Failed to fetch %r", t, exc_info=True)
        return None


"""
Main loop starts things up and sends some optional test results to the console

"""
if __name__ == "__main__":
    if slack_client.rtm_connect(with_team_state=False):
        print("DSpace bot connected and running!")
        #fetch_repos()
        #print(fetch_pullrequest(2048))
        #print(fetch_jiraissue(3734))
        #print(fetch_commit('6d1b695'))
        print(search_pulls_simple("repo:DSpace/DSpace is:open label:\"quick win\" milestone:6.4 sort:interaction"))

        # Read bot's user ID by calling Web API method `auth.test`
        dspace_bot_id = slack_client.api_call("auth.test")["user_id"]
        while True:
            #command, data, channel = parse_bot_commands(slack_client.rtm_read())
            magic_phrase = parse_slack_events(slack_client.rtm_read())
            if magic_phrase:
                print "Got a magic phrase: %s" % magic_phrase['name']
                handle_command(magic_phrase['name'], magic_phrase, magic_phrase['channel'])
            #if command:
            #    handle_command(command, data, channel)
            time.sleep(RTM_READ_DELAY)
    else:
        print("Connection failed. Exception traceback printed above.")
