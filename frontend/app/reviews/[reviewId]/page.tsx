import type { Metadata } from "next";
import { ReviewDetail } from "@/components/ReviewDetail";

export const metadata: Metadata = {
  title: "Review Detail",
};

export default async function ReviewDetailPage({ params }: { params: Promise<{ reviewId: string }> }) {
  const { reviewId } = await params;
  return <ReviewDetail reviewId={reviewId} />;
}
