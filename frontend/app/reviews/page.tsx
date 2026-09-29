import type { Metadata } from "next";
import { ReviewQueue } from "@/components/ReviewQueue";

export const metadata: Metadata = {
  title: "Reviews",
};

export default function ReviewsPage() {
  return <ReviewQueue />;
}
