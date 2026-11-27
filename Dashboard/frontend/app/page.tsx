"use client";

import dynamic from "next/dynamic";

/* The dashboard is live, clock-driven and pointer-driven: render it in the browser only. */
const Dashboard = dynamic(() => import("./Dashboard"), { ssr: false });

export default function Page() {
  return <Dashboard />;
}
