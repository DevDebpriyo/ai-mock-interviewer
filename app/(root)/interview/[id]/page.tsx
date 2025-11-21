import Image from "next/image";
import { redirect } from "next/navigation";

import { randomUUID } from "crypto";

import Agent from "@/components/Agent";
import { getRandomInterviewCover } from "@/lib/utils";

import {
  createFeedback,
  getFeedbackByInterviewId,
  getInterviewById,
} from "@/lib/actions/general.action";
import { getCurrentUser } from "@/lib/actions/auth.action";
import DisplayTechIcons from "@/components/DisplayTechIcons";
import { Button } from "@/components/ui/button";

const InterviewDetails = async ({ params }: RouteParams) => {
  const { id } = await params;

  const user = await getCurrentUser();
  if (!user?.id) redirect("/sign-in");

  const interview = await getInterviewById(id);
  if (!interview) redirect("/");

  const feedback = await getFeedbackByInterviewId({
    interviewId: id,
    userId: user.id,
  });

  const roomName = `prepwise-conduct-${id}-${randomUUID()}`;

  const handleGenerateFeedback = async () => {
    "use server";

    await createFeedback({
      interviewId: id,
      userId: user.id,
      feedbackId: feedback?.id,
    });

    redirect(`/interview/${id}/feedback`);
  };

  return (
    <>
      <div className="flex flex-row gap-4 justify-between">
        <div className="flex flex-row gap-4 items-center max-sm:flex-col">
          <div className="flex flex-row gap-4 items-center">
            <Image
              src={getRandomInterviewCover()}
              alt="cover-image"
              width={40}
              height={40}
              className="rounded-full object-cover size-[40px]"
            />
            <h3 className="capitalize">{interview.role} Interview</h3>
          </div>

          <DisplayTechIcons techStack={interview.techstack} />
        </div>

        <p className="bg-dark-200 px-4 py-2 rounded-lg h-fit">
          {interview.type}
        </p>
      </div>

      <Agent
        userName={user.name ?? "Prepwise Candidate"}
        userId={user.id}
        roomName={roomName}
        mode="conduct"
        interviewId={id}
      />

      <form action={handleGenerateFeedback} className="mt-6 flex justify-end">
        <Button className="btn-primary">Generate Feedback</Button>
      </form>
    </>
  );
};

export default InterviewDetails;
