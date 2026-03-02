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
    .header h1 {{ color: #F97316; margin: 0; font-size: 24px; letter-spacing: 1px; }}
    .content {{ padding: 32px 24px; color: #1E293B; line-height: 1.6; }}
    .content h2 {{ color: #0F172A; margin-top: 0; }}
    .btn {{ display: inline-block; padding: 14px 28px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 16px; margin: 8px 4px; }}
    .btn-confirm {{ background: #F97316; color: white !important; }}
    .btn-edit {{ background: #3B82F6; color: white !important; }}
    .btn-reject {{ background: #EF4444; color: white !important; }}
    .btn-sign {{ background: #10B981; color: white !important; }}
    .btn-view {{ background: #6366F1; color: white !important; }}
    .card {{ border: 1px solid #E2E8F0; border-radius: 8px; padding: 16px; margin: 16px 0; background: #F8FAFC; }}
    .card-label {{ font-size: 12px; color: #94A3B8; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }}
    .card-value {{ font-size: 15px; color: #1E293B; font-weight: 500; }}
    .footer {{ padding: 16px 24px; text-align: center; color: #94A3B8; font-size: 12px; border-top: 1px solid #E2E8F0; }}
    .badge {{ display: inline-block; padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }}
    .badge-high {{ background: #FEF3C7; color: #92400E; }}
    .badge-medium {{ background: #DBEAFE; color: #1E40AF; }}
    .timestamp {{ color: #94A3B8; font-size: 13px; }}
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
      <p>SiteTrace &mdash; AI-Powered Change Order Management</p>
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
    """Notification 1: Change detected — contractor action required."""
    confidence_badge = (
        '<span class="badge badge-high">High Confidence</span>'
        if confidence >= 0.85
        else '<span class="badge badge-medium">Review Recommended</span>'
    )

    content = f"""
    <h2>Change Detected</h2>
    <p>Hi {contractor_name},</p>
    <p>SiteTrace detected a potential change in <strong>{project_name}</strong>:</p>

    <div class="card">
      <div class="card-label">Description</div>
      <div class="card-value">{description}</div>
    </div>

    {"<div class='card'><div class='card-label'>Area</div><div class='card-value'>" + area + "</div></div>" if area else ""}

    <div class="card">
      <div class="card-label">AI Confidence</div>
      <div class="card-value">{confidence:.0%} {confidence_badge}</div>
    </div>

    {evidence_html}

    <p style="text-align: center; margin-top: 24px;">
      <a href="{confirm_url}" class="btn btn-confirm">Confirm</a>
      <a href="{edit_url}" class="btn btn-edit">Edit &amp; Confirm</a>
      <a href="{reject_url}" class="btn btn-reject">Reject</a>
    </p>

    <p class="timestamp">
      These links expire in 48 hours. You can also manage this from your dashboard.
    </p>
    """
    return BASE_TEMPLATE.format(content=content)


def render_change_confirmed(
    contractor_name: str,
    project_name: str,
    description: str,
    order_number: str,
    co_url: str,
) -> str:
    """Notification 2: Change confirmed, Change Order created."""
    content = f"""
    <h2>Change Order Created</h2>
    <p>Hi {contractor_name},</p>
    <p>Your confirmed change in <strong>{project_name}</strong> has been converted to a Change Order.</p>

    <div class="card">
      <div class="card-label">Change Order</div>
      <div class="card-value">{order_number}</div>
    </div>

    <div class="card">
      <div class="card-label">Description</div>
      <div class="card-value">{description}</div>
    </div>

    <p><strong>Next steps:</strong></p>
    <ol>
      <li>Add cost line items to the Change Order</li>
      <li>Review the generated PDF</li>
      <li>Send to your client for signature</li>
    </ol>

    {"<p style='text-align: center;'><a href='" + co_url + "' class='btn btn-view'>View Change Order</a></p>" if co_url else ""}
    """
    return BASE_TEMPLATE.format(content=content)


def render_client_sign_request(
    client_name: str,
    contractor_name: str,
    project_name: str,
    order_number: str,
    description: str,
    total: str,
    currency: str,
    sign_url: str,
    pdf_url: str,
) -> str:
    """Notification 3: Sent to CLIENT for signature."""
    content = f"""
    <h2>Change Order &mdash; Signature Required</h2>
    <p>Hi {client_name},</p>
    <p><strong>{contractor_name}</strong> has submitted a Change Order for your project <strong>{project_name}</strong>:</p>

    <div class="card">
      <div class="card-label">Change Order</div>
      <div class="card-value">{order_number}</div>
    </div>

    <div class="card">
      <div class="card-label">Description</div>
      <div class="card-value">{description}</div>
    </div>

    <div class="card">
      <div class="card-label">Total</div>
      <div class="card-value" style="font-size: 20px; color: #F97316;">{currency} {total}</div>
    </div>

    {"<p><a href='" + pdf_url + "'>View Full PDF</a></p>" if pdf_url else ""}

    <p style="text-align: center; margin-top: 24px;">
      <a href="{sign_url}" class="btn btn-sign">Approve &amp; Sign</a>
    </p>

    <p class="timestamp">
      By clicking "Approve &amp; Sign", you digitally approve this change order.
      Your IP address and timestamp will be recorded. This link expires in 48 hours.
    </p>
    """
    return BASE_TEMPLATE.format(content=content)


def render_change_closed(
    contractor_name: str,
    project_name: str,
    order_number: str,
    client_name: str,
    signed_at: str,
    total: str,
    currency: str,
    co_url: str,
) -> str:
    """Notification 4: Client signed — change order closed."""
    content = f"""
    <h2>Change Order Signed</h2>
    <p>Hi {contractor_name},</p>
    <p><strong>{client_name}</strong> has approved and signed Change Order
    <strong>{order_number}</strong> for <strong>{project_name}</strong>.</p>

    <div class="card">
      <div class="card-label">Change Order</div>
      <div class="card-value">{order_number}</div>
    </div>

    <div class="card">
      <div class="card-label">Approved Amount</div>
      <div class="card-value" style="font-size: 20px; color: #10B981;">{currency} {total}</div>
    </div>

    <div class="card">
      <div class="card-label">Signed At</div>
      <div class="card-value">{signed_at}</div>
    </div>

    <p style="text-align: center; margin-top: 24px;">
      <a href="{co_url}" class="btn btn-view">View Change Order</a>
    </p>

    <p class="timestamp">
      This change order is now closed. The signed PDF is available in your dashboard.
    </p>
    """
    return BASE_TEMPLATE.format(content=content)


def render_document_bulletin(
    recipient_name: str,
    project_name: str,
    bulletin_number: str,
    title: str,
    summary_text: str,
    affected_areas: list[dict],
    order_number: str,
    pdf_url: str | None = None,
) -> str:
    """Document Bulletin: Notify team members about approved changes affecting documents."""
    affected_html = ""
    if affected_areas:
        rows = ""
        for area in affected_areas:
            category = area.get("category", "general").replace("_", " ").title()
            desc = area.get("description", "")
            action = area.get("action", "Verify documents are up to date")
            rows += f"""
            <tr>
              <td style="padding: 8px; border-bottom: 1px solid #E2E8F0;">
                <span class="badge badge-high">{category}</span>
              </td>
              <td style="padding: 8px; border-bottom: 1px solid #E2E8F0;">{desc}</td>
              <td style="padding: 8px; border-bottom: 1px solid #E2E8F0; color: #DC2626; font-weight: 600;">{action}</td>
            </tr>"""

        affected_html = f"""
        <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
          <thead>
            <tr style="background: #0F172A; color: white;">
              <th style="padding: 8px; text-align: left; font-size: 11px;">Category</th>
              <th style="padding: 8px; text-align: left; font-size: 11px;">Description</th>
              <th style="padding: 8px; text-align: left; font-size: 11px;">Action Required</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>"""

    # Convert summary markdown-like formatting to HTML
    summary_html = summary_text.replace("\n", "<br>")

    content = f"""
    <div style="background: #FEF2F2; border: 2px solid #DC2626; border-radius: 8px; padding: 16px; margin-bottom: 20px;">
      <h2 style="color: #DC2626; margin: 0 0 8px 0;">Document Bulletin {bulletin_number}</h2>
      <p style="margin: 0; font-weight: 600;">{title}</p>
    </div>

    <p>Hi {recipient_name},</p>
    <p>A change order has been approved for <strong>{project_name}</strong> that affects project documents.
    Please review the details below and take the required actions.</p>

    <div class="card">
      <div class="card-label">Change Order</div>
      <div class="card-value">{order_number}</div>
    </div>

    <h3 style="color: #0F172A; border-bottom: 1px solid #E2E8F0; padding-bottom: 6px;">What Changed</h3>
    <div style="line-height: 1.6;">{summary_html}</div>

    {affected_html}

    {"<p style='text-align: center; margin-top: 24px;'><a href='" + pdf_url + "' class='btn btn-view'>View Full Bulletin PDF</a></p>" if pdf_url else ""}

    <p class="timestamp">
      This bulletin was automatically generated by SiteTrace when Change Order {order_number} was signed.
      Please verify you are working with the latest document versions before continuing work.
    </p>
    """
    return BASE_TEMPLATE.format(content=content)
