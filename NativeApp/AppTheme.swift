import SwiftUI
import UIKit

enum AppTheme {
    static let background = Color(uiColor: .systemGroupedBackground)
    static let card = Color(uiColor: .secondarySystemGroupedBackground)
    static let surface = Color(uiColor: .systemBackground)
    static let surfaceElevated = Color(uiColor: .secondarySystemBackground)
    static let text = Color(uiColor: .label)
    static let textSecondary = Color(uiColor: .secondaryLabel)
    static let textMuted = Color(uiColor: .tertiaryLabel)
    static let border = Color(uiColor: .separator).opacity(0.42)
    static let borderSoft = Color(uiColor: .separator).opacity(0.2)
    static let bubble = Color(uiColor: .tertiarySystemFill)
    static let disabled = Color(uiColor: .systemGray5)
    static let onBadge = Color.white
    static let onStatusAction = Color.white
    static let primaryAction = Color(uiColor: UIColor { traits in
        traits.userInterfaceStyle == .dark ? .white : .black
    })
    static let onPrimaryAction = Color(uiColor: UIColor { traits in
        traits.userInterfaceStyle == .dark ? .black : .white
    })
    static let green = Color(uiColor: .systemGreen)
    static let red = Color(uiColor: .systemRed)
    static let orangeBackground = Color(uiColor: UIColor { traits in
        traits.userInterfaceStyle == .dark
            ? UIColor(red: 72 / 255, green: 49 / 255, blue: 27 / 255, alpha: 1)
            : UIColor(red: 250 / 255, green: 241 / 255, blue: 232 / 255, alpha: 1)
    })
    static let orangeText = Color(uiColor: UIColor { traits in
        traits.userInterfaceStyle == .dark
            ? UIColor(red: 255 / 255, green: 189 / 255, blue: 122 / 255, alpha: 1)
            : UIColor(red: 107 / 255, green: 74 / 255, blue: 46 / 255, alpha: 1)
    })
    static let shadowSubtle = Color.black.opacity(0.04)
    static let shadowCard = Color.black.opacity(0.055)
    static let shadowElevated = Color.black.opacity(0.06)
    static let shadowFloating = Color.black.opacity(0.1)
    static let drawerScrim = Color.black

    enum Spacing {
        static let xxs: CGFloat = 4
        static let xs: CGFloat = 8
        static let sm: CGFloat = 12
        static let md: CGFloat = 16
        static let lg: CGFloat = 20
        static let xl: CGFloat = 24
        static let xxl: CGFloat = 32
    }

    enum Radius {
        static let notice: CGFloat = 12
        static let chip: CGFloat = 14
        static let preview: CGFloat = 16
        static let bubble: CGFloat = 18
        static let panel: CGFloat = 20
        static let media: CGFloat = 22
        static let chatCard: CGFloat = 22
        static let composer: CGFloat = 24
        static let card: CGFloat = 24
        static let sheet: CGFloat = 28
        static let featureCard: CGFloat = 28
    }

    enum Typography {
        static let nav = Font.headline.weight(.semibold)
        static let navCompact = Font.subheadline.weight(.semibold)
        static let title = Font.largeTitle.weight(.bold)
        static let cardTitle = Font.title2.weight(.bold)
        static let body = Font.body
        static let caption = Font.caption
        static let action = Font.subheadline.weight(.semibold)
        static let primaryButton = Font.callout.weight(.semibold)
        static let inlineControl = Font.caption.weight(.semibold)
        static let meta = Font.caption.weight(.medium)
        static let drawerActionTitle = Font.subheadline.weight(.semibold)
        static let drawerRowTitle = Font.subheadline.weight(.medium)
        static let drawerBadge = Font.caption2.weight(.semibold)
        static let recommendationSubtitle = Font.subheadline.weight(.medium)
        static let productHeroTitle = Font.title2.weight(.semibold)
        static let productHeroSubtitle = Font.subheadline
        static let productEmptyTitle = Font.headline.weight(.semibold)
        static let productEmptyMessage = Font.subheadline
        static let productActionTitle = Font.headline.weight(.semibold)
        static let productActionSubtitle = Font.footnote
        static let productRowTitle = Font.callout.weight(.semibold)
        static let productRowBody = Font.footnote
        static let productStatus = Font.caption.weight(.semibold)
        static let productMeta = Font.caption2.weight(.medium)
    }

    enum Icon {
        static let tiny = Font.system(size: 12, weight: .semibold)
        static let small = Font.system(size: 13, weight: .semibold)
        static let inline = Font.system(size: 14, weight: .semibold)
        static let action = Font.system(size: 15, weight: .semibold)
        static let clear = Font.system(size: 16, weight: .semibold)
        static let composer = Font.system(size: 17, weight: .semibold)
        static let menu = Font.system(size: 17, weight: .semibold)
        static let deckMenu = Font.system(size: 18, weight: .semibold)
        static let productAction = Font.system(size: 20, weight: .semibold)
        static let productHero = Font.system(size: 22, weight: .semibold)
        static let productEmpty = Font.system(size: 24, weight: .semibold)
        static let back = Font.system(size: 22, weight: .medium)
        static let toolbar = Font.system(size: 20, weight: .semibold)
        static let avatar = Font.system(size: 28, weight: .medium)
        static let row = Font.system(size: 17, weight: .semibold)
    }

    enum TouchTarget {
        static let minimum: CGFloat = 44
    }
}

extension View {
    func appScreenBackground() -> some View {
        background(AppTheme.background.ignoresSafeArea())
    }

    func appMinimumTouchTarget() -> some View {
        frame(minWidth: AppTheme.TouchTarget.minimum, minHeight: AppTheme.TouchTarget.minimum)
            .contentShape(Rectangle())
    }
}

enum AppHaptics {
    @MainActor
    static func selection() {
        UISelectionFeedbackGenerator().selectionChanged()
    }

    @MainActor
    static func success() {
        UINotificationFeedbackGenerator().notificationOccurred(.success)
    }

    @MainActor
    static func warning() {
        UINotificationFeedbackGenerator().notificationOccurred(.warning)
    }
}
