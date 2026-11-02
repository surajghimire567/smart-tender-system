import React from "react";

const STATUS_CLASS = {
  draft: "status-pill status-draft",
  published: "status-pill status-published",
  closed: "status-pill status-closed",
  awarded: "status-pill status-awarded",
};

export default function StatusPill({ status }) {
  return <span className={STATUS_CLASS[status] || "status-pill"}>{status}</span>;
}
