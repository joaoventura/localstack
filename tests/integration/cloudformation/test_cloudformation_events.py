import json
import logging
import os

import jinja2

from localstack.testing.aws.cloudformation_utils import load_template_file
from localstack.utils.aws import aws_stack
from localstack.utils.common import short_uid
from localstack.utils.generic.wait_utils import wait_until

LOG = logging.getLogger(__name__)


# TODO: refactor file and remove this compatibility fn
def load_template_raw(file_name: str):
    return load_template_file(os.path.join(os.path.dirname(__file__), "../templates", file_name))


def test_eventbus_policies(
    cfn_client,
    events_client,
    cleanup_stacks,
    cleanup_changesets,
    is_change_set_created_and_available,
    is_stack_created,
):
    stack_name = f"stack-{short_uid()}"
    change_set_name = f"change-set-{short_uid()}"
    event_bus_name = f"event-bus-{short_uid()}"
    template_rendered = jinja2.Template(load_template_raw("eventbridge_policy.yaml")).render(
        event_bus_name=event_bus_name
    )

    response = cfn_client.create_change_set(
        StackName=stack_name,
        ChangeSetName=change_set_name,
        TemplateBody=template_rendered,
        ChangeSetType="CREATE",
    )

    change_set_id = response["Id"]
    stack_id = response["StackId"]

    try:
        wait_until(is_change_set_created_and_available(change_set_id))
        cfn_client.execute_change_set(ChangeSetName=change_set_id)
        wait_until(is_stack_created(stack_id))
        assert (
            cfn_client.describe_stacks(StackName=stack_id)["Stacks"][0]["StackStatus"]
            == "CREATE_COMPLETE"
        )

        # check that both statements were added
        describe_response = events_client.describe_event_bus(Name=event_bus_name)
        policy = json.loads(describe_response["Policy"])
        assert len(policy["Statement"]) == 2

        # verify physical resource ID creation
        pol1_description = cfn_client.describe_stack_resource(
            StackName=stack_id, LogicalResourceId="eventPolicy"
        )
        pol2_description = cfn_client.describe_stack_resource(
            StackName=stack_id, LogicalResourceId="eventPolicy2"
        )
        assert (
            pol1_description["StackResourceDetail"]["PhysicalResourceId"]
            != pol2_description["StackResourceDetail"]["PhysicalResourceId"]
        )

        # TODO: Fix cloudformation change set update status
        # TODO: Fix second changeset execution (should delete resource in stack's _resource_states)
        # delete one of the 2 statements and check if the other still exists
        # template_rendered_single_policy = jinja2.Template(load_template_raw("eventbridge_policy_singlepolicy.yaml")).render(
        #     event_bus_name=event_bus_name
        # )
        # change_set_name = f"change-set-update-{short_uid()}"
        # response = cfn_client.create_change_set(
        #     StackName=stack_name,
        #     ChangeSetName=change_set_name,
        #     TemplateBody=template_rendered_single_policy,
        # )
        # change_set_id = response["Id"]
        # wait_until(is_change_set_created_and_available(change_set_id))
        # cfn_client.execute_change_set(ChangeSetName=change_set_id)
        # cfn_client.get_waiter("stack_create_complete").wait(StackName=stack_id, WaiterConfig={'Delay': 5, 'MaxAttempts': 10})  # TODO: should be get_waiter("stack_update_complete")
        #
        # describe_response = events_client.describe_event_bus(Name=event_bus_name)
        # policy = json.loads(describe_response['Policy'])
        # assert len(policy['Statement']) == 1

    finally:
        cleanup_changesets([change_set_id])
        cleanup_stacks([stack_id])


def test_eventbus_policy_statement(
    cfn_client,
    events_client,
    cleanup_stacks,
    cleanup_changesets,
    is_change_set_created_and_available,
    is_stack_created,
):
    stack_name = f"stack-{short_uid()}"
    change_set_name = f"change-set-{short_uid()}"
    event_bus_name = f"event-bus-{short_uid()}"
    statement_id = f"statement-{short_uid()}"
    template_rendered = jinja2.Template(
        load_template_raw("eventbridge_policy_statement.yaml")
    ).render(event_bus_name=event_bus_name, statement_id=statement_id)

    response = cfn_client.create_change_set(
        StackName=stack_name,
        ChangeSetName=change_set_name,
        TemplateBody=template_rendered,
        ChangeSetType="CREATE",
    )

    change_set_id = response["Id"]
    stack_id = response["StackId"]

    try:
        wait_until(is_change_set_created_and_available(change_set_id))
        cfn_client.execute_change_set(ChangeSetName=change_set_id)
        wait_until(is_stack_created(stack_id))
        assert (
            cfn_client.describe_stacks(StackName=stack_id)["Stacks"][0]["StackStatus"]
            == "CREATE_COMPLETE"
        )

        describe_response = events_client.describe_event_bus(Name=event_bus_name)
        policy = json.loads(describe_response["Policy"])
        assert policy["Version"] == "2012-10-17"
        assert len(policy["Statement"]) == 1
        statement = policy["Statement"][0]
        assert statement["Sid"] == statement_id
        assert statement["Action"] == "events:PutEvents"
        assert statement["Principal"] == "*"
        assert statement["Effect"] == "Allow"
        assert event_bus_name in statement["Resource"]

    finally:
        cleanup_changesets([change_set_id])
        cleanup_stacks([stack_id])


def test_event_rule_to_logs(
    cfn_client,
    events_client,
    logs_client,
    cleanup_stacks,
    cleanup_changesets,
    is_change_set_created_and_available,
    is_stack_created,
):
    stack_name = f"stack-{short_uid()}"
    change_set_name = f"change-set-{short_uid()}"
    event_rule_name = f"event-rule-{short_uid()}"
    log_group_name = f"log-group-{short_uid()}"
    message_token = f"test-message-{short_uid()}"
    event_bus_name = f"bus-{short_uid()}"
    resource_policy_name = f"policy-{short_uid()}"

    template_rendered = jinja2.Template(load_template_raw("events_loggroup.yaml")).render(
        event_rule_name=event_rule_name,
        log_group_name=log_group_name,
        event_bus_name=event_bus_name,
        resource_policy_name=resource_policy_name,
    )

    response = cfn_client.create_change_set(
        StackName=stack_name,
        ChangeSetName=change_set_name,
        TemplateBody=template_rendered,
        ChangeSetType="CREATE",
    )

    change_set_id = response["Id"]
    stack_id = response["StackId"]

    try:
        wait_until(is_change_set_created_and_available(change_set_id))
        cfn_client.execute_change_set(ChangeSetName=change_set_id)
        wait_until(is_stack_created(stack_id))
        assert (
            cfn_client.describe_stacks(StackName=stack_id)["Stacks"][0]["StackStatus"]
            == "CREATE_COMPLETE"
        )

        log_groups = logs_client.describe_log_groups(logGroupNamePrefix=log_group_name)["logGroups"]
        log_group_names = [lg["logGroupName"] for lg in log_groups]
        assert log_group_name in log_group_names

        resp = events_client.put_events(
            Entries=[
                {
                    "Source": "unittest",
                    "Resources": [],
                    "DetailType": "ls-detail-type",
                    "Detail": json.dumps({"messagetoken": message_token}),
                    "EventBusName": event_bus_name,
                }
            ]
        )
        assert len(resp["Entries"]) == 1
        wait_until(
            lambda: len(logs_client.describe_log_streams(logGroupName=log_group_name)["logStreams"])
            > 0,
            1.0,
            5,
            "linear",
        )
        log_streams = logs_client.describe_log_streams(logGroupName=log_group_name)["logStreams"]
        assert len(log_streams) == 1

        log_events = logs_client.get_log_events(
            logGroupName=log_group_name, logStreamName=log_streams[0]["logStreamName"]
        )
        assert message_token in log_events["events"][0]["message"]

    finally:
        cleanup_changesets([change_set_id])
        cleanup_stacks([stack_id])


def test_event_rule_creation_without_target(cfn_client, deploy_cfn_template):
    event_rule_name = f"event-rule-{short_uid()}"
    deployed = deploy_cfn_template(
        template_path=os.path.join(
            os.path.dirname(__file__), "../templates/events_rule_without_targets.yaml"
        ),
        parameters={"EventRuleName": event_rule_name},
    )
    stack_name = deployed.stack_name

    assert (
        cfn_client.describe_stacks(StackName=stack_name)["Stacks"][0]["StackStatus"]
        == "CREATE_COMPLETE"
    )


def test_cfn_event_bus_resource(events_client, deploy_cfn_template):
    def _assert(expected_len):
        rs = events_client.list_event_buses()
        event_buses = [eb for eb in rs["EventBuses"] if eb["Name"] == "my-test-bus"]
        assert len(event_buses) == expected_len
        rs = events_client.list_connections()
        connections = [con for con in rs["Connections"] if con["Name"] == "my-test-conn"]
        assert len(connections) == expected_len

    stack = deploy_cfn_template(
        template_path=os.path.join(os.path.dirname(__file__), "../templates/template31.yaml")
    )
    _assert(1)

    stack.destroy()
    _assert(0)


TEST_TEMPLATE_16 = """
AWSTemplateFormatVersion: 2010-09-09
Resources:
  MyBucket:
    Type: 'AWS::S3::Bucket'
    Properties:
      BucketName: %s
  ScheduledRule:
    Type: 'AWS::Events::Rule'
    Properties:
      Name: %s
      ScheduleExpression: rate(10 minutes)
      State: ENABLED
      Targets:
        - Id: TargetBucketV1
          Arn: !GetAtt "MyBucket.Arn"
"""

TEST_TEMPLATE_18 = """
AWSTemplateFormatVersion: 2010-09-09
Resources:
  TestStateMachine:
    Type: "AWS::StepFunctions::StateMachine"
    Properties:
      RoleArn: %s
      DefinitionString:
        !Sub
        - |-
          {
            "StartAt": "state1",
            "States": {
              "state1": {
                "Type": "Pass",
                "Result": "Hello World",
                "End": true
              }
            }
          }
        - {}
  ScheduledRule:
    Type: AWS::Events::Rule
    Properties:
      ScheduleExpression: "cron(0/1 * * * ? *)"
      State: ENABLED
      Targets:
        - Id: TestStateMachine
          Arn: !Ref TestStateMachine
"""


def test_cfn_handle_events_rule(events_client, deploy_cfn_template):
    bucket_name = f"target-{short_uid()}"
    rule_prefix = f"s3-rule-{short_uid()}"
    rule_name = f"{rule_prefix}-{short_uid()}"

    stack = deploy_cfn_template(
        template=TEST_TEMPLATE_16 % (bucket_name, rule_name),
    )

    rs = events_client.list_rules(NamePrefix=rule_prefix)
    assert rule_name in [rule["Name"] for rule in rs["Rules"]]

    target_arn = aws_stack.s3_bucket_arn(bucket_name)  # TODO: !
    rs = events_client.list_targets_by_rule(Rule=rule_name)
    assert target_arn in [target["Arn"] for target in rs["Targets"]]

    # clean up
    stack.destroy()
    rs = events_client.list_rules(NamePrefix=rule_prefix)
    assert rule_name not in [rule["Name"] for rule in rs["Rules"]]


def test_cfn_handle_events_rule_without_name(events_client, deploy_cfn_template):
    rs = events_client.list_rules()
    rule_names = [rule["Name"] for rule in rs["Rules"]]

    stack = deploy_cfn_template(
        template=TEST_TEMPLATE_18 % aws_stack.role_arn("sfn_role"),  # TODO: !
    )

    rs = events_client.list_rules()
    new_rules = [rule for rule in rs["Rules"] if rule["Name"] not in rule_names]
    assert len(new_rules) == 1
    rule = new_rules[0]

    assert rule["ScheduleExpression"] == "cron(0/1 * * * ? *)"

    stack.destroy()

    rs = events_client.list_rules()
    assert rule["Name"] not in [r["Name"] for r in rs["Rules"]]
