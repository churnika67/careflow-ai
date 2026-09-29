import type { Metadata } from "next";
import { Claims } from "@/components/Claims";

export const metadata: Metadata = {
  title: "Claims",
};

export default function ClaimsPage() {
  return <Claims />;
}
