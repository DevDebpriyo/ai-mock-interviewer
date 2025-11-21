import { randomUUID } from "crypto";
import { redirect } from "next/navigation";

import Agent from "@/components/Agent";
import { getCurrentUser } from "@/lib/actions/auth.action";

const Page = async () => {
  const user = await getCurrentUser();
  if (!user?.id) redirect("/sign-in");

  const roomName = `prepwise-create-${user.id}-${randomUUID()}`;

  return (
    <>
      <h3>Design your next mock interview</h3>
      <p className="text-light-100">
        Talk with Prepwise Coach to define the role, experience level, and focus
        areas for your next practice session. We&apos;ll save everything
        automatically.
      </p>

      <Agent
        userName={user.name}
        userId={user.id}
        roomName={roomName}
        mode="create"
      />
    </>
  );
};

export default Page;
