import type { ImageAsset } from "@prisma/client";
import { prisma } from "../db.js";
import type { BoundTop1Decision, Top1Decision } from "./pipi/schemas.js";

export type CandidateFact = {
  placeKey: string | null;
  itemKey: string | null;
  imageAssetId: string;
  label: string;
  isAiGenerated: boolean;
  verificationStatus: string;
};

export async function listUsableImageAssets(rawText: string): Promise<ImageAsset[]> {
  const assets = await prisma.imageAsset.findMany({
    where: {
      isAiGenerated: false,
      verificationStatus: "verified",
    },
    orderBy: { createdAt: "asc" },
  });

  const matched = assets.filter((asset) => matchesText(asset, rawText));
  return matched.length > 0 ? matched : assets;
}

export function toCandidateFacts(assets: ImageAsset[]): CandidateFact[] {
  return assets.map((asset) => ({
    placeKey: asset.placeKey,
    itemKey: asset.itemKey,
    imageAssetId: asset.id,
    label: [asset.placeKey, asset.itemKey].filter(Boolean).join(" / "),
    isAiGenerated: asset.isAiGenerated,
    verificationStatus: asset.verificationStatus,
  }));
}

export function bindImageAsset(decision: Top1Decision, assets: ImageAsset[]): ImageAsset | null {
  const exact = assets.find((asset) =>
    (!decision.placeKey || asset.placeKey === decision.placeKey)
    && (!decision.itemKey || asset.itemKey === decision.itemKey)
  );
  if (exact) {
    return exact;
  }

  const title = `${decision.title} ${decision.subtitle} ${decision.reason}`;
  const semantic = assets.find((asset) => matchesText(asset, title));
  return semantic ?? assets[0] ?? null;
}

export function curatedTop1ForQuestion(rawText: string, assets: ImageAsset[]): BoundTop1Decision | null {
  const text = rawText.toLowerCase();
  const datongAsset = assets.find((asset) =>
    asset.placeKey === "datong-xijindao"
    && asset.itemKey === "knife-cut-noodles-meatball"
  );

  if (datongAsset && (text.includes("大同") || text.includes("喜晋道"))) {
    return {
      kind: "top1",
      title: "刀削面 + 肉丸子",
      subtitle: "你在大同,这组最稳。",
      reason: "喜晋道场景已经足够明确,数据库里有已验证的本地招牌资产,不需要再把问题丢给真人。",
      bullets: ["刀削面是大同招牌", "肉丸子让这顿更完整", "到店后直接点,少看菜单"],
      warning: "不想吃面食或猪肉就别选。",
      confidence: 0.88,
      placeKey: datongAsset.placeKey ?? undefined,
      itemKey: datongAsset.itemKey ?? undefined,
      imageAssetId: datongAsset.id,
      followups: ["为什么?", "换个清淡的"],
    };
  }

  return null;
}

function matchesText(asset: ImageAsset, rawText: string) {
  const text = rawText.toLowerCase();
  const placeKey = asset.placeKey ?? "";
  const itemKey = asset.itemKey ?? "";

  if (placeKey.includes("datong") || itemKey.includes("knife-cut")) {
    return text.includes("大同")
      || text.includes("喜晋道")
      || text.includes("刀削面")
      || text.includes("面");
  }

  if (placeKey.includes("korea") || placeKey.includes("seongsu")) {
    return text.includes("韩国")
      || text.includes("首尔")
      || text.includes("明洞")
      || text.includes("圣水")
      || text.includes("逛街");
  }

  return false;
}
