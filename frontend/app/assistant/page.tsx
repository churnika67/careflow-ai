import type { Metadata } from "next";
import { Assistant } from "@/components/Assistant";

export const metadata: Metadata = {
  title: "CareFlow Assistant",
};

export default function AssistantPage() {
  return <Assistant />;
}
