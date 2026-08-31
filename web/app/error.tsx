"use client";

import { AlertCircle } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="p-6">
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertTitle>Can&apos;t reach the Forgeway API</AlertTitle>
        <AlertDescription className="space-y-3">
          <p>
            This page couldn&apos;t load data from the backend. Most likely the API isn&apos;t
            running yet, or isn&apos;t reachable at the URL this page is configured to use
            (<code className="rounded bg-muted px-1 py-0.5">NEXT_PUBLIC_API_BASE_URL</code>,
            currently{" "}
            <code className="rounded bg-muted px-1 py-0.5">
              {process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"}
            </code>
            ). See the README&apos;s &quot;Running the demo&quot; section — the backend needs to be
            started in its own terminal before (or alongside) this one.
          </p>
          <p className="font-mono text-xs text-muted-foreground">{error.message}</p>
          <Button variant="outline" size="sm" onClick={() => reset()}>
            Try again
          </Button>
        </AlertDescription>
      </Alert>
    </div>
  );
}
