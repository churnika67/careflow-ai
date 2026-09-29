import type { Metadata } from "next";
import { PatientData } from "@/components/PatientData";

export const metadata: Metadata = {
  title: "Patient Data",
};

export default function PatientDataPage() {
  return <PatientData />;
}
