import SwiftUI

enum AppTheme {
    static let background = Color(red: 250 / 255, green: 250 / 255, blue: 250 / 255)
    static let card = Color.white
    static let surface = Color.white
    static let surfaceElevated = Color(red: 255 / 255, green: 255 / 255, blue: 255 / 255)
    static let text = Color(red: 17 / 255, green: 17 / 255, blue: 17 / 255)
    static let textSecondary = Color(red: 95 / 255, green: 95 / 255, blue: 95 / 255)
    static let textMuted = Color(red: 154 / 255, green: 154 / 255, blue: 154 / 255)
    static let border = Color(red: 236 / 255, green: 236 / 255, blue: 236 / 255)
    static let borderSoft = Color(red: 241 / 255, green: 241 / 255, blue: 241 / 255)
    static let bubble = Color(red: 240 / 255, green: 240 / 255, blue: 238 / 255)
    static let disabled = Color(red: 229 / 255, green: 229 / 255, blue: 229 / 255)
    static let green = Color(red: 31 / 255, green: 138 / 255, blue: 76 / 255)
    static let red = Color(red: 226 / 255, green: 48 / 255, blue: 58 / 255)
    static let orangeBackground = Color(red: 250 / 255, green: 241 / 255, blue: 232 / 255)
    static let orangeText = Color(red: 107 / 255, green: 74 / 255, blue: 46 / 255)

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
        static let chip: CGFloat = 14
        static let composer: CGFloat = 24
        static let card: CGFloat = 24
        static let sheet: CGFloat = 28
    }

    enum Typography {
        static let nav = Font.system(size: 18, weight: .semibold)
        static let title = Font.system(size: 28, weight: .bold)
        static let cardTitle = Font.system(size: 24, weight: .bold)
        static let body = Font.system(size: 16)
        static let caption = Font.system(size: 13)
    }

    enum Icon {
        static let toolbar = Font.system(size: 20, weight: .semibold)
        static let row = Font.system(size: 17, weight: .semibold)
    }
}

extension View {
    func appScreenBackground() -> some View {
        background(AppTheme.background.ignoresSafeArea())
    }
}
