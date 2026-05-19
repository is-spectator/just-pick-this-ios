import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

export async function seedImageAssets() {
  await prisma.imageAsset.upsert({
    where: { id: "11111111-1111-4111-8111-111111111111" },
    update: {
      sourceType: "curated",
      url: "https://images.unsplash.com/photo-1569718212165-3a8278d5f624",
      thumbnailUrl: "https://images.unsplash.com/photo-1569718212165-3a8278d5f624?w=480",
      sourceUrl: "https://unsplash.com/photos/1569718212165-3a8278d5f624",
      credit: "Curated placeholder, replace before production",
      isAiGenerated: false,
      verificationStatus: "verified",
      placeKey: "datong-xijindao",
      itemKey: "knife-cut-noodles-meatball",
    },
    create: {
      id: "11111111-1111-4111-8111-111111111111",
      sourceType: "curated",
      url: "https://images.unsplash.com/photo-1569718212165-3a8278d5f624",
      thumbnailUrl: "https://images.unsplash.com/photo-1569718212165-3a8278d5f624?w=480",
      sourceUrl: "https://unsplash.com/photos/1569718212165-3a8278d5f624",
      credit: "Curated placeholder, replace before production",
      isAiGenerated: false,
      verificationStatus: "verified",
      placeKey: "datong-xijindao",
      itemKey: "knife-cut-noodles-meatball",
    },
  });

  await prisma.imageAsset.upsert({
    where: { id: "22222222-2222-4222-8222-222222222222" },
    update: {
      sourceType: "curated",
      url: "https://images.unsplash.com/photo-1517154421773-0529f29ea451",
      thumbnailUrl: "https://images.unsplash.com/photo-1517154421773-0529f29ea451?w=480",
      sourceUrl: "https://unsplash.com/photos/1517154421773-0529f29ea451",
      credit: "Curated placeholder, replace before production",
      isAiGenerated: false,
      verificationStatus: "verified",
      placeKey: "korea-seongsu",
      itemKey: "shopping-street",
    },
    create: {
      id: "22222222-2222-4222-8222-222222222222",
      sourceType: "curated",
      url: "https://images.unsplash.com/photo-1517154421773-0529f29ea451",
      thumbnailUrl: "https://images.unsplash.com/photo-1517154421773-0529f29ea451?w=480",
      sourceUrl: "https://unsplash.com/photos/1517154421773-0529f29ea451",
      credit: "Curated placeholder, replace before production",
      isAiGenerated: false,
      verificationStatus: "verified",
      placeKey: "korea-seongsu",
      itemKey: "shopping-street",
    },
  });
}

async function main() {
  await seedImageAssets();
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main()
    .then(async () => {
      await prisma.$disconnect();
    })
    .catch(async (error) => {
      console.error(error);
      await prisma.$disconnect();
      process.exit(1);
    });
}
