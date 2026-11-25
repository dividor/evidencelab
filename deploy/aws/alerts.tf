# Email alerts. With alert_emails set, each region that has an alarm gets an
# SNS topic named <name>-alerts (always including the deployment's region),
# and every address is subscribed to it. Each alarm sends to the topic in its
# own region. AWS emails every address once per topic to confirm.
#
# bedrock_alarms: one CloudWatch alarm per model and level, on the total over
# a rolling hour. CloudWatch evaluates them every minute, so an alert arrives
# within minutes of the level being passed. Hours with no use count as normal.

locals {
  alert_regions = length(var.alert_emails) == 0 ? [] : distinct(concat(
    [var.region],
    [for a in values(var.bedrock_alarms) : coalesce(a.region, var.region)],
  ))

  bedrock_alarm_metrics = {
    input_tokens_per_hour  = { metric = "InputTokenCount", what = "input tokens" }
    output_tokens_per_hour = { metric = "OutputTokenCount", what = "output tokens" }
    invocations_per_hour   = { metric = "Invocations", what = "requests" }
  }

  bedrock_alarms = merge(concat([{}], [
    for id, a in var.bedrock_alarms : {
      for setting, m in local.bedrock_alarm_metrics : "${id} ${m.what}" => {
        model_id = id
        region   = coalesce(a.region, var.region)
        metric   = m.metric
        what     = m.what
        limit    = a[setting]
      } if a[setting] != null
    }
  ])...)
}

resource "aws_sns_topic" "alerts" {
  for_each = toset(local.alert_regions)

  region = each.key
  name   = "${var.name}-alerts"
}

resource "aws_sns_topic_subscription" "alerts" {
  for_each = {
    for pair in setproduct(local.alert_regions, var.alert_emails) :
    "${pair[0]} ${pair[1]}" => { region = pair[0], email = pair[1] }
  }

  region    = each.value.region
  topic_arn = aws_sns_topic.alerts[each.value.region].arn
  protocol  = "email"
  endpoint  = each.value.email
}

resource "aws_cloudwatch_metric_alarm" "bedrock" {
  for_each = local.bedrock_alarms

  region            = each.value.region
  alarm_name        = "${var.name} Bedrock ${each.key} per hour"
  alarm_description = "Amazon Bedrock model ${each.value.model_id} had more than ${each.value.limit} ${each.value.what} in an hour in Evidence Lab deployment ${var.name}. Who used it: the admin Token Usage tab. The level is bedrock_alarms in the deployment's settings."

  namespace           = "AWS/Bedrock"
  metric_name         = each.value.metric
  dimensions          = { ModelId = each.value.model_id }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = each.value.limit
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts[each.value.region].arn]
}

# The daily AI limit (AI_DAILY_COST_LIMIT_USD in extra_environment): the first
# AI request the api or the MCP server refuses each day logs a line starting
# "AI daily limit reached". With alert_emails set, a metric filter counts that
# line in both log groups and an alarm emails the addresses.
locals {
  ai_daily_limit_alarm = length(var.alert_emails) > 0 && contains(keys(var.extra_environment), "AI_DAILY_COST_LIMIT_USD")
}

resource "aws_cloudwatch_log_metric_filter" "ai_daily_limit" {
  for_each = local.ai_daily_limit_alarm ? toset(["api", "mcp"]) : toset([])

  name           = "${var.name}-${each.key}-ai-daily-limit"
  log_group_name = aws_cloudwatch_log_group.this[each.key].name
  pattern        = "\"AI daily limit reached\""

  metric_transformation {
    name      = "AiDailyLimitReached"
    namespace = "EvidenceLab/${var.name}"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "ai_daily_limit" {
  count = local.ai_daily_limit_alarm ? 1 : 0

  alarm_name        = "${var.name} AI daily limit reached"
  alarm_description = "Evidence Lab deployment ${var.name} reached its daily AI limit (AI_DAILY_COST_LIMIT_USD): AI features are paused until 00:00 UTC, search still works. Who used it: the admin Token Usage tab."

  namespace           = "EvidenceLab/${var.name}"
  metric_name         = "AiDailyLimitReached"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts[var.region].arn]
}
