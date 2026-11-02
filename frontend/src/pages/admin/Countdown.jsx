import React, { useEffect, useState } from "react";

function remaining(deadline) {
  const seconds = Math.max(0, Math.floor((Date.parse(deadline) - Date.now()) / 1000));
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  return { seconds, days, hours, minutes, secs };
}

/** Display-only countdown. The server decides whether a tender is open. */
export default function Countdown({ deadline, status }) {
  const [left, setLeft] = useState(() => remaining(deadline));

  useEffect(() => {
    const tick = () => setLeft(remaining(deadline));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [deadline]);

  if (status !== "published") return <span>—</span>;
  if (left.seconds <= 0) return <span>Deadline reached · server status refresh pending</span>;
  return (
    <span>
      {left.days}d {String(left.hours).padStart(2, "0")}h {String(left.minutes).padStart(2, "0")}m {String(left.secs).padStart(2, "0")}s
    </span>
  );
}
