# SiteTrace email templates — HTML for Resend
# Colors: primary #F97316, background #0F172A, light #F8FAFC

BASE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 0; background: #F8FAFC; }}
    .container {{ max-width: 600px; margin: 0 auto; background: white; }}
    .header {{ background: #0F172A; padding: 24px; text-align: center; }}
    .header h1 {{ color: #F97316; margin: 0; font-size: 24px; }}
    .content {{ padding: 32px 24px; }}
    .btn {{ display: inline-block; padding: 14px 28px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 16px; margin: 8px 4px; }}
    .btn-confirm {{ background: #F97316; color: white; }}
    .btn-reject {{ background: #EF4444; color: white; }}
    .btn-sign {{ background: #10B981; color: white; }}
    .evidence {{ border: 1px solid #E2E8F0; border-radius: 8px; padding: 16px; margin: 16px 0; background: #F8FAFC; }}
    .footer {{ padding: 16px 24px; text-align: center; color: #94A3B8; font-size: 12px; border-top: 1px solid #E2E8F0; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>SiteTrace</h1>
    </div>
    <div class="content">
      {content}
    </div>
    <div class="footer">
      <p>SiteTrace — AI-Powered Change Order Management</p>
      <p>This is an automated notification. Do not reply to this email.</p>
    </div>
  </div>
</body>
</html>
"""


def render_change_proposed(
    contractor_name: str,
    project_name: str,
    description: str,
    area: str | None,
    confidence: float,
    confirm_url: str,
    reject_url: str,
    edit_url: str,
    evidence_html: str = "",
) -> str:
    content = f"""
    <h2>Change Detected</h2>
    <p>Hi {contractor_name},</p>
    <p>A potential change has been detected in <strong>{project_name}</strong>:</p>

    <div class="evidence">
      <p><strong>Description:</strong> {description}</p>
      {"<p><strong>Area:</strong> " + area + "</p>" if area else ""}
      <p><strong>AI Confidence:</strong> {confidence:.0%}</p>
    </div>

    {evidence_html}

    <p style="text-align: center; margin-top: 24px;">
      <a href="{confirm_url}" class="btn btn-confirm">Confirm Change</a>
      <a href="{edit_url}" class="btn" style="background: #3B82F6; color: white;">Edit & Confirm</a>
      <a href="{reject_url}" class="btn btn-reject">Reject</a>
    </p>

    <p style="color: #94A3B8; font-size: 13px; margin-top: 16px;">
      These links expire in 48 hours. You can also manage this change from your dashboard.
    </p>
    """
    return BASE_TEMPLATE.format(content=content)
