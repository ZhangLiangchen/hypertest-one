"use client";
import { useParams } from "next/navigation";
import { MemoryWorkspace } from "./memory-workspace";

export default function ProjectMemoryPage() {
  const { projectId } = useParams<{ projectId: string }>();
  return <MemoryWorkspace key={projectId} projectId={projectId} />;
}
