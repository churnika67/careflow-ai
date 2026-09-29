import type { Metadata } from "next";
import { AskCareFlow } from "@/components/AskCareFlow";

export const metadata: Metadata = {
  title: "Ask CareFlow",
};

export default function AskPage() {
  return <AskCareFlow />;
}
