import { z } from "zod";

export const Top1DecisionSchema = z.object({
  kind: z.literal("top1"),
  title: z.string().min(1),
  subtitle: z.string().min(1),
  reason: z.string().min(1),
  bullets: z.array(z.string().min(1)).min(1).max(4),
  warning: z.string().optional(),
  confidence: z.number().min(0).max(1).optional(),
  placeKey: z.string().optional(),
  itemKey: z.string().optional(),
  followups: z.array(z.string().min(1)).max(3).optional(),
});

export const AskDraftDecisionSchema = z.object({
  kind: z.literal("ask_draft"),
  title: z.string().min(1),
  contextText: z.string().min(1),
  reason: z.string().optional(),
});

export const PipiQuestionDecisionSchema = z.discriminatedUnion("kind", [
  Top1DecisionSchema,
  AskDraftDecisionSchema,
]);

export const PipiFinalDecisionSchema = Top1DecisionSchema;

export type Top1Decision = z.infer<typeof Top1DecisionSchema>;
export type AskDraftDecision = z.infer<typeof AskDraftDecisionSchema>;
export type PipiQuestionDecision = z.infer<typeof PipiQuestionDecisionSchema>;

export type BoundTop1Decision = Top1Decision & {
  imageAssetId: string;
};

export type BoundQuestionDecision = BoundTop1Decision | AskDraftDecision;
